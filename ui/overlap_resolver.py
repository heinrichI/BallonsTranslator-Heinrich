"""
OverlapResolver — извлечённый из SceneTextManager.

Содержит логику разрешения перекрытий между flow-блоками.
Путём сужения контрольных точек большего блока.

НЕ зависит от Qt widgets — только от QPointF и TextBlkItem.
"""

import logging
from typing import List

from qtpy.QtCore import QPointF

from utils.logger import logger as LOGGER

QUIET_UI = True

# Доля сдвига для ближайших точек выше/ниже зоны пересечения.
# Полный сдвиг получают только точки в зоне; соседи сдвигаются
# частично — чтобы граница шла косой (плавный изгиб, а не вертикальная
# ступенька), т.к. текст рендерится лучше на плавных кривых.
NEIGHBOR_SHIFT_FACTOR = 0.5


def _debug(msg, *args, **kwargs):
    if not QUIET_UI:
        LOGGER.debug(msg, *args, **kwargs)


class OverlapResolver:
    """
    Разрешение перекрытий между flow-блоками.
    
    Алгоритм:
    1. Определяет перекрытие между new_item и каждым existing item
    2. Находит больший блок по площади
    3. Сужает сторону большего блока, ближайшую к меньшему:
       - точки с y в зоне пересечения сдвигаются на полный overlap_x;
       - ближайшие точки строго выше/ниже зоны — на overlap_x * NEIGHBOR_SHIFT_FACTOR
         (плавный косой переход вместо резкого излома);
       - остальные точки не трогаются.
    4. Обновляет layout большего блока

    Защита от повторных сдвигов: если control points блока уже не лежат
    на прямоугольнике (x-координаты точек одной стороны не равны между
    собой), значит блок уже сужался ранее — повторный сдвиг для него
    не применяется (_points_already_shifted).
    """

    # Точность сравнения x-координат контрольных точек (защита от float-шума).
    _X_EPS = 3  # знаков после запятой при округлении

    def _points_already_shifted(self, item) -> bool:
        """True, если control points блока уже сдвигались (не прямоугольник).

        У свежесозданного блока все левые точки имеют одинаковый x и все
        правые — одинаковый x. Если x внутри стороны различаются, блок
        уже был сужен (overlap-сдвигом или вручную) — повторно сужать нельзя.
        """
        left_xs = {round(p.x(), self._X_EPS) for p in item._left_points}
        right_xs = {round(p.x(), self._X_EPS) for p in item._right_points}
        return len(left_xs) > 1 or len(right_xs) > 1

    def resolve_overlaps(self, new_item, existing_items: List) -> None:
        """
        Разрешает перекрытия new_item с existing_items.
        
        Args:
            new_item: Новый текстовый блок (TextBlkItem)
            existing_items: Список существующих блоков
        """
        if not self._is_flow_item(new_item):
            return
        
        new_pos = new_item.pos()
        new_left = min(p.x() for p in new_item._left_points) + new_pos.x()
        new_right = max(p.x() for p in new_item._right_points) + new_pos.x()
        new_top = min(p.y() for p in new_item._left_points) + new_pos.y()
        new_bottom = max(p.y() for p in new_item._left_points) + new_pos.y()
        
        new_text = new_item.toPlainText()[:30]
        overlaps_found = 0
        
        for existing in existing_items:
            if existing is new_item:
                continue
            if not self._is_flow_item(existing):
                continue
            
            ex_pos = existing.pos()
            ex_left = min(p.x() for p in existing._left_points) + ex_pos.x()
            ex_right = max(p.x() for p in existing._right_points) + ex_pos.x()
            ex_top = min(p.y() for p in existing._left_points) + ex_pos.y()
            ex_bottom = max(p.y() for p in existing._left_points) + ex_pos.y()
            
            # Check overlap
            overlap_x = max(0, min(new_right, ex_right) - max(new_left, ex_left))
            overlap_y = max(0, min(new_bottom, ex_bottom) - max(new_top, ex_top))
            if overlap_x <= 0 or overlap_y <= 0:
                continue

            # Guard: если control points любого из блоков уже не на прямоугольнике,
            # значит overlap-сдвиг для него уже применялся ранее — повторно
            # сужать нельзя (иначе точки будут сдвигаться кумулятивно).
            if self._points_already_shifted(new_item) or self._points_already_shifted(existing):
                LOGGER.debug("[OVERLAP] Skipping already-shifted block pair ('%s', '%s')",
                            new_text, existing.toPlainText()[:30])
                continue

            new_area = (new_right - new_left) * (new_bottom - new_top)
            ex_area = (ex_right - ex_left) * (ex_bottom - ex_top)
            bigger_area = max(new_area, ex_area)
            overlap_area = overlap_x * overlap_y
            if bigger_area > 0 and overlap_area / bigger_area >= 0.5:
                existing_text = existing.toPlainText()[:30]
                LOGGER.debug("[OVERLAP] Skipping: overlap too large relative to bigger block (%.0f%%) between '%s' and '%s'",
                            overlap_area / bigger_area * 100, new_text, existing_text)
                continue

            overlaps_found += 1
            existing_text = existing.toPlainText()[:30]
            LOGGER.debug("[OVERLAP] Resolving overlap between '%s' (area=%.0f) and '%s' (area=%.0f) (overlap_x=%.1f, overlap_y=%.1f)",
                        new_text, new_area, existing_text, ex_area, overlap_x, overlap_y)
            
            if new_area >= ex_area:
                bigger = new_item
                bigger_pos = new_pos
                smaller_center_x = (ex_left + ex_right) / 2
            else:
                bigger = existing
                bigger_pos = ex_pos
                smaller_center_x = (new_left + new_right) / 2
            
            bigger_center_x = (min(p.x() for p in bigger._left_points) + bigger_pos.x() +
                               max(p.x() for p in bigger._right_points) + bigger_pos.x()) / 2
            
            # Narrow bigger block's side closest to the smaller block
            if smaller_center_x > bigger_center_x:
                # Smaller is to the right → narrow bigger's RIGHT side
                side = 'right'
                points = bigger._right_points
            else:
                # Smaller is to the left → narrow bigger's LEFT side
                side = 'left'
                points = bigger._left_points
            
            # Overlap zone in bigger block's local y coordinates
            overlap_top_local = max(new_top, ex_top) - bigger_pos.y()
            overlap_bottom_local = min(new_bottom, ex_bottom) - bigger_pos.y()
            
            # Check if smaller block is fully contained in bigger's y-range
            bigger_top_local = min(p.y() for p in bigger._left_points)
            bigger_bottom_local = max(p.y() for p in bigger._left_points)
            smaller_top = min(new_top, ex_top)
            smaller_bottom = max(new_bottom, ex_bottom)
            smaller_top_local = smaller_top - bigger_pos.y()
            smaller_bottom_local = smaller_bottom - bigger_pos.y()
            fully_contained = smaller_top_local >= bigger_top_local and smaller_bottom_local <= bigger_bottom_local
            
            # Ближайшие точки строго вне зоны (по y, а не по индексу —
            # пользователь может двигать/добавлять хендлы, порядок списка не
            # гарантирован). Они получают частичный сдвиг — косой переход.
            neighbor_above_idx = None
            neighbor_below_idx = None
            if not fully_contained:
                above = [i for i, pt in enumerate(points) if pt.y() < overlap_top_local]
                below = [i for i, pt in enumerate(points) if pt.y() > overlap_bottom_local]
                if above:
                    neighbor_above_idx = max(above, key=lambda i: points[i].y())
                if below:
                    neighbor_below_idx = min(below, key=lambda i: points[i].y())

            zone_idx = 'all' if fully_contained else [
                i for i, pt in enumerate(points)
                if overlap_top_local <= pt.y() <= overlap_bottom_local
            ]
            LOGGER.debug("[OVERLAP] Side=%s shift plan: zone pts=%s (full %.1f), neighbor above pt=%s / below pt=%s (%.1f)",
                        side, zone_idx, overlap_x,
                        neighbor_above_idx, neighbor_below_idx,
                        overlap_x * NEIGHBOR_SHIFT_FACTOR)

            for i, pt in enumerate(points):
                if fully_contained or (overlap_top_local <= pt.y() <= overlap_bottom_local):
                    shift = overlap_x
                elif i == neighbor_above_idx or i == neighbor_below_idx:
                    shift = overlap_x * NEIGHBOR_SHIFT_FACTOR
                else:
                    continue
                if side == 'right':
                    new_pt_x = max(pt.x() - shift, 10)
                else:
                    new_pt_x = min(pt.x() + shift, bigger._right_points[i].x() - 10)
                points[i] = QPointF(new_pt_x, pt.y())

            # Update layout of the bigger block
            bigger._update_flow_layout()

            bigger_left_new = min(p.x() for p in bigger._left_points) + bigger_pos.x()
            bigger_right_new = max(p.x() for p in bigger._right_points) + bigger_pos.x()
            bigger_top_new = min(p.y() for p in bigger._left_points) + bigger_pos.y()
            bigger_bottom_new = max(p.y() for p in bigger._left_points) + bigger_pos.y()
            bigger_area_new = (bigger_right_new - bigger_left_new) * (bigger_bottom_new - bigger_top_new)
            bigger_text = bigger.toPlainText()[:30]
            LOGGER.debug("[OVERLAP] After resolution: '%s' area %.0f -> %.0f",
                        bigger_text,
                        new_area if bigger is new_item else ex_area,
                        bigger_area_new)
        
        if overlaps_found > 0:
            LOGGER.debug("[OVERLAP] Resolved %d overlap(s) for block '%s'", overlaps_found, new_text)
    
    def _is_flow_item(self, item) -> bool:
        """Check if item is a flow text block with control points."""
        return hasattr(item, '_left_points') and item._left_points
