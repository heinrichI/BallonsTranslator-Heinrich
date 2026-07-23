"""
Тесты синхронизации координат blk.xyxy после перемещения/ресайза блоков.

Регрессионные тесты на баг, когда OCR и Save PNG использовали устаревшие
координаты blk.xyxy после перемещения блока или изменения размера через
flow-хендлы.

Исправления:
1. onSavePngBlk использует absBoundingRect() вместо устаревшего blk.xyxy
2. MoveBlkItemsCommand синхронизирует blk.xyxy при redo/undo
3. FlowTextBlkItem._update_flow_layout записывает blk.xyxy из контрольных точек

Запуск:
    set QT_QPA_PLATFORM=offscreen
    cd j:\\Comic translate\\BallonsTranslator
    myenv\\Scripts\\python.exe -m pytest tests/ui/test_block_xyxy_sync.py -v
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtWidgets import QApplication, QGraphicsScene, QGraphicsView
from qtpy.QtCore import Qt, QPointF

from utils.textblock import TextBlock
from ui.flow_textitem import FlowTextBlkItem
from ui.textitem import TextBlkItem


# ── Фикстуры ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    """Один QApplication на всю сессию (offscreen)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def scene(qapp):
    """Свежая QGraphicsScene для каждого теста."""
    s = QGraphicsScene()
    view = QGraphicsView(s)
    view.resize(2000, 2000)
    yield s
    s.clear()


def _make_blk(xyxy=(0, 0, 400, 200), text="Hello world test text", font_size=24.0):
    """Создать TextBlock с заданными координатами."""
    x1, y1, x2, y2 = xyxy
    blk = TextBlock([x1, y1, x2, y2])
    blk.lines = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
    blk.translation = text
    blk.fontformat.size = font_size
    blk.fontformat.font_family = "Arial"
    blk._bounding_rect = [x1, y1, x2 - x1, y2 - y1]
    return blk


def _make_flow_item(scene, xyxy=(0, 0, 400, 200), text="Hello world test text", font_size=24.0):
    """Создать FlowTextBlkItem и добавить в сцену."""
    blk = _make_blk(xyxy, text, font_size)
    item = FlowTextBlkItem(blk, idx=0, show_rect=False)
    scene.addItem(item)
    return item


def _make_text_item(scene, xyxy=(0, 0, 400, 200), text="Hello world test text", font_size=24.0):
    """Создать TextBlkItem и добавить в сцену."""
    blk = _make_blk(xyxy, text, font_size)
    item = TextBlkItem(blk, idx=0, show_rect=False)
    scene.addItem(item)
    return item


# ── Исправление 2: MoveBlkItemsCommand синхронизирует blk.xyxy ──

class TestMoveBlkItemsCommandXyxySync:
    """MoveBlkItemsCommand должен обновлять blk.xyxy после setPos()."""

    def _get_xyxy(self, item):
        bx, by, bw, bh = item.absBoundingRect()
        return [int(bx), int(by), int(bx + bw), int(by + bh)]

    def test_redo_syncs_xyxy_after_move(self, scene):
        """После redo перемещения blk.xyxy должен совпадать с визуальной позицией."""
        from ui.textedit_commands import MoveBlkItemsCommand

        item = _make_flow_item(scene, xyxy=(100, 100, 300, 200))
        shape_ctrl = MagicMock()
        shape_ctrl.blk_item = item

        # Запомнить старые координаты
        old_xyxy = list(item.blk.xyxy)

        # Создать команду (захватывает старые/новые позиции)
        old_pos = item.pos()
        item.setPos(QPointF(old_pos.x() + 150, old_pos.y() + 80))
        cmd = MoveBlkItemsCommand([item], shape_ctrl)

        # Redo применяет новую позицию — blk.xyxy должен обновиться
        cmd.redo()

        expected = self._get_xyxy(item)
        assert item.blk.xyxy == expected, (
            f"После redo: blk.xyxy={item.blk.xyxy} != expected={expected}"
        )

    def test_undo_syncs_xyxy_after_move_back(self, scene):
        """После undo перемещения blk.xyxy должен вернуться к исходной позиции."""
        from ui.textedit_commands import MoveBlkItemsCommand

        item = _make_flow_item(scene, xyxy=(100, 100, 300, 200))
        shape_ctrl = MagicMock()
        shape_ctrl.blk_item = item

        old_pos = item.pos()
        item.setPos(QPointF(old_pos.x() + 150, old_pos.y() + 80))
        cmd = MoveBlkItemsCommand([item], shape_ctrl)

        cmd.redo()

        # Undo возвращает обратно — blk.xyxy должен синхронизироваться
        cmd.undo()

        expected = self._get_xyxy(item)
        assert item.blk.xyxy == expected, (
            f"После undo: blk.xyxy={item.blk.xyxy} != expected={expected}"
        )

    def test_move_then_ocr_uses_correct_region(self, scene):
        """После перемещения blk.xyxy должен совпадать с тем, что OCR обрежет."""
        from ui.textedit_commands import MoveBlkItemsCommand

        item = _make_flow_item(scene, xyxy=(50, 50, 250, 150))
        shape_ctrl = MagicMock()
        shape_ctrl.blk_item = item

        old_pos = item.pos()
        item.setPos(QPointF(old_pos.x() + 200, old_pos.y() + 100))
        cmd = MoveBlkItemsCommand([item], shape_ctrl)
        cmd.redo()

        # blk.xyxy должен быть в перемещённой позиции
        x1, y1, x2, y2 = item.blk.xyxy
        bx, by, bw, bh = item.absBoundingRect()
        assert x1 == int(bx) and y1 == int(by), (
            f"blk.xyxy левый верхний ({x1},{y1}) != визуальный ({int(bx)},{int(by)})"
        )
        assert x2 == int(bx + bw) and y2 == int(by + bh), (
            f"blk.xyxy правый нижний ({x2},{y2}) != визуальный ({int(bx + bw)},{int(by + bh)})"
        )

    def test_multiple_blocks_move_independently(self, scene):
        """Перемещение одного блока не затрагивает координаты другого."""
        from ui.textedit_commands import MoveBlkItemsCommand

        item1 = _make_flow_item(scene, xyxy=(0, 0, 200, 100))
        item2 = _make_flow_item(scene, xyxy=(300, 0, 500, 100))
        shape_ctrl = MagicMock()
        shape_ctrl.blk_item = item1

        # Переместить только item1
        old_pos = item1.pos()
        item1.setPos(QPointF(old_pos.x() + 100, old_pos.y() + 50))
        cmd = MoveBlkItemsCommand([item1], shape_ctrl)
        cmd.redo()

        bx, by, bw, bh = item1.absBoundingRect()
        expected1 = [int(bx), int(by), int(bx + bw), int(by + bh)]
        assert item1.blk.xyxy == expected1

        # Координаты item2 остались на месте (x не изменился)
        assert item2.blk.xyxy[0] == 300
        assert item2.blk.xyxy[2] == 500


# ── Исправление 3: _update_flow_layout синхронизирует blk.xyxy ──

class TestFlowResizeXyxySync:
    """_update_flow_layout должен записывать blk.xyxy из контрольных точек."""

    def test_flow_resize_updates_xyxy(self, scene):
        """При сужении правой границы blk.xyxy отражает новую ширину."""
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))

        # Сузить правую границу
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(250, pt.y())
        item._update_flow_layout()

        x1, y1, x2, y2 = item.blk.xyxy
        assert x2 - x1 <= 260, (
            f"Ширина blk.xyxy={x2 - x1} должна быть ~250 после сужения"
        )

    def test_flow_resize_top_bottom_updates_xyxy(self, scene):
        """При перемещении верхней границы вниз blk.xyxy отражает новое y1."""
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))

        # Переместить верхнюю границу вниз
        for i, pt in enumerate(item._left_points):
            item._left_points[i] = QPointF(pt.x(), pt.y() + 30)
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(pt.x(), pt.y() + 30)
        item._update_flow_layout()

        x1, y1, x2, y2 = item.blk.xyxy
        assert y1 >= 20, (
            f"blk.xyxy y1={y1} должен быть >= 20 после смещения верха вниз"
        )

    def test_flow_resize_matches_absboundingrect(self, scene):
        """После ресайза blk.xyxy должен совпадать с absBoundingRect()."""
        item = _make_flow_item(scene, xyxy=(100, 50, 400, 250))

        # Сузить справа
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(200, pt.y())
        item._update_flow_layout()

        bx, by, bw, bh = item.absBoundingRect()
        expected = [int(bx), int(by), int(bx + bw), int(by + bh)]

        assert item.blk.xyxy == expected, (
            f"blk.xyxy={item.blk.xyxy} != absBoundingRect={expected}"
        )

    def test_flow_resize_left_boundary_updates_xyxy(self, scene):
        """При сужении левой границы x1 blk.xyxy увеличивается."""
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))

        # Запомнить начальный x1
        x1_before = item.blk.xyxy[0]

        # Переместить левую границу вправо
        for i, pt in enumerate(item._left_points):
            item._left_points[i] = QPointF(80, pt.y())
        item._update_flow_layout()

        x1, y1, x2, y2 = item.blk.xyxy
        # x1 должен увеличиться (левая граница сдвинута вправо)
        assert x1 > x1_before, (
            f"blk.xyxy x1={x1} должен быть > {x1_before} после сдвига левой границы"
        )

    def test_flow_points_saved_match_xyxy(self, scene):
        """Диапазон blk.left_points/right_points должен совпадать с blk.xyxy."""
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))

        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(250, pt.y() + 10)
        item._update_flow_layout()

        # Контрольные точки в локальных координатах, blk.xyxy — в координатах сцены
        pos = item.pos()
        all_pts = item._left_points + item._right_points
        local_x = min(p.x() for p in all_pts)
        local_y = min(p.y() for p in all_pts)
        local_w = max(p.x() for p in all_pts) - local_x
        local_h = max(p.y() for p in all_pts) - local_y

        expected_xyxy = [
            int(pos.x() + local_x), int(pos.y() + local_y),
            int(pos.x() + local_x + local_w), int(pos.y() + local_y + local_h)
        ]

        assert item.blk.xyxy == expected_xyxy, (
            f"blk.xyxy={item.blk.xyxy} != вычислено из flow points={expected_xyxy}"
        )


class TestFlowResizeLinesSync:
    """_update_flow_layout должен также обновлять blk.lines (для get_transformed_region в OCR)."""

    def test_flow_resize_updates_blk_lines(self, scene):
        """После ресайза полигон blk.lines должен соответствовать новым размерам."""
        import numpy as np
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))

        # Сузить правую границу
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(250, pt.y())
        item._update_flow_layout()

        # blk.lines должен обновиться — извлекаем bbox из полигона lines
        lines = np.array(item.blk.lines)
        lx1, ly1 = lines[..., 0].min(), lines[..., 1].min()
        lx2, ly2 = lines[..., 0].max(), lines[..., 1].max()
        lines_w = lx2 - lx1

        # Ширина из lines должна совпадать с шириной xyxy
        x1, y1, x2, y2 = item.blk.xyxy
        assert abs(lines_w - (x2 - x1)) <= 2, (
            f"Ширина lines={lines_w} != ширина xyxy={x2 - x1}"
        )

    def test_move_updates_blk_lines(self, scene):
        """После перемещения полигон blk.lines должен быть в новой позиции."""
        import numpy as np
        from ui.textedit_commands import MoveBlkItemsCommand

        item = _make_flow_item(scene, xyxy=(100, 100, 300, 200))
        shape_ctrl = MagicMock()
        shape_ctrl.blk_item = item

        old_pos = item.pos()
        item.setPos(QPointF(old_pos.x() + 150, old_pos.y() + 80))
        cmd = MoveBlkItemsCommand([item], shape_ctrl)
        cmd.redo()

        # blk.lines должен быть в перемещённой позиции
        lines = np.array(item.blk.lines)
        lx1 = lines[..., 0].min()
        x1, y1, x2, y2 = item.blk.xyxy
        assert abs(lx1 - x1) <= 2, (
            f"lines x1={lx1} != xyxy x1={x1}"
        )


# ── Исправление: absBoundingRect использует контрольные точки ──


class TestAbsBoundingRectControlPoints:
    """absBoundingRect() должен использовать контрольные точки для x, а не только pos().

    Корневая причина: при сужении левой границы через flow-хендлы pos() остаётся
    прежним, но контрольные точки двигаются. absBoundingRect() использовал pos()
    для x, возвращая устаревший x1=508 вместо сужённого x1=215. Весь downstream-код
    (OCR, сохранение, синхронизация) опирался на это и получал неверные координаты.
    """

    def test_left_narrow_absboundingrect_uses_control_points(self, scene):
        """После сужения левой границы, absBoundingRect x1 = pos.x + cp.x."""
        item = _make_flow_item(scene, xyxy=(100, 100, 500, 200))

        # Переместить левую границу вправо (сужение слева)
        for i, pt in enumerate(item._left_points):
            item._left_points[i] = QPointF(80, pt.y())
        item._update_flow_layout()

        abr = item.absBoundingRect()
        # x1 должен быть из левой контрольной точки (80) + pos().x(), а не только из pos()
        x1 = abr[0]
        cp_x = min(p.x() for p in item._left_points)
        expected_x1 = int(item.pos().x() + cp_x)
        assert x1 == expected_x1, (
            f"absBoundingRect x1={x1} != pos.x + cp.x = {expected_x1}"
        )

    def test_right_narrow_absboundingrect_width_matches_control_points(self, scene):
        """После сужения правой границы, ширина absBoundingRect = диапазон контрольных точек."""
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))

        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(200, pt.y())
        item._update_flow_layout()

        abr = item.absBoundingRect()
        w = abr[2]  # ширина
        cp_w = max(p.x() for p in item._left_points + item._right_points) - \
               min(p.x() for p in item._left_points + item._right_points)
        assert abs(w - cp_w) <= 2, (
            f"Ширина absBoundingRect={w} != ширина контрольных точек={cp_w}"
        )

    def test_both_sides_narrow_absboundingrect_correct(self, scene):
        """После сужения с обеих сторон absBoundingRect совпадает с контрольными точками."""
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))

        for i, pt in enumerate(item._left_points):
            item._left_points[i] = QPointF(60, pt.y())
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(300, pt.y())
        item._update_flow_layout()

        abr = item.absBoundingRect()
        x1, y1, w, h = abr
        all_xs = [p.x() for p in item._left_points] + [p.x() for p in item._right_points]
        all_ys = [p.y() for p in item._left_points] + [p.y() for p in item._right_points]
        expected_x = int(item.pos().x() + min(all_xs))
        expected_w = max(all_xs) - min(all_xs)
        expected_h = max(all_ys) - min(all_ys)

        assert x1 == expected_x, f"x1={x1} != {expected_x}"
        assert abs(w - expected_w) <= 2, f"Ширина={w} != {expected_w}"
        assert abs(h - expected_h) <= 2, f"Высота={h} != {expected_h}"

    def test_absboundingrect_matches_xyxy_after_narrow(self, scene):
        """После сужения absBoundingRect и blk.xyxy должны совпадать."""
        item = _make_flow_item(scene, xyxy=(100, 50, 500, 250))

        for i, pt in enumerate(item._left_points):
            item._left_points[i] = QPointF(80, pt.y())
        item._update_flow_layout()

        bx, by, bw, bh = item.absBoundingRect()
        xyxy_from_abr = [int(bx), int(by), int(bx + bw), int(by + bh)]
        assert item.blk.xyxy == xyxy_from_abr, (
            f"blk.xyxy={item.blk.xyxy} != из absBoundingRect={xyxy_from_abr}"
        )

    def test_update_textblk_list_uses_narrowed_coords(self, scene):
        """update_textblk_list должен записывать сужённые координаты, а не полную ширину."""
        from ui.block_manager import BlockManager
        from unittest.mock import MagicMock

        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))
        # Сузить левую границу
        for i, pt in enumerate(item._left_points):
            item._left_points[i] = QPointF(80, pt.y())
        item._update_flow_layout()

        # Создать мок-проект
        proj = MagicMock()
        cbl = []
        proj.current_block_list.return_value = cbl

        mgr = BlockManager.__new__(BlockManager)
        mgr.textblk_item_list = [item]
        mgr.pairwidget_list = [MagicMock()]
        mgr.pairwidget_list[0].e_source.toPlainText.return_value = "test"

        mgr.update_textblk_list(proj)

        saved_blk = cbl[0]
        # Сохранённые xyxy должны использовать сужённый x1, а не полную ширину
        cp_x = min(p.x() for p in item._left_points)
        expected_x1 = int(item.pos().x() + cp_x)
        assert saved_blk.xyxy[0] == expected_x1, (
            f"Сохранённый xyxy x1={saved_blk.xyxy[0]} != expected {expected_x1}"
        )


class TestSavePngUsesCurrentPosition:
    """onSavePngBlk должен использовать absBoundingRect, а не устаревший blk.xyxy."""

    def test_absboundingrect_used_for_crop(self, scene):
        """Симуляция onSavePngBlk — используется текущая позиция."""
        item = _make_flow_item(scene, xyxy=(100, 100, 300, 200))

        # Переместить элемент через setPos (blk.xyxy останется устаревшим без исправления)
        old_pos = item.pos()
        item.setPos(QPointF(old_pos.x() + 50, old_pos.y() + 30))

        # Симуляция исправленного onSavePngBlk
        bx, by, bw, bh = item.absBoundingRect()
        crop_xyxy = [int(bx), int(by), int(bx + bw), int(by + bh)]

        # Область кропа должна быть в НОВОЙ позиции, а не в старой
        assert crop_xyxy[0] >= 140, (
            f"Crop x1={crop_xyxy[0]} должен быть >= 140 после перемещения на +50"
        )
        assert crop_xyxy[1] >= 120, (
            f"Crop y1={crop_xyxy[1]} должен быть >= 120 после перемещения на +30"
        )

    def test_flow_resize_crop_uses_correct_region(self, scene):
        """После ресайза область кропа совпадает с сужённым блоком."""
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))

        # Сузить справа
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(200, pt.y())
        item._update_flow_layout()

        bx, by, bw, bh = item.absBoundingRect()
        crop_xyxy = [int(bx), int(by), int(bx + bw), int(by + bh)]

        # Ширина должна быть ~200, а не 400
        crop_w = crop_xyxy[2] - crop_xyxy[0]
        assert crop_w <= 220, (
            f"Ширина кропа={crop_w} должна быть ~200 после сужения"
        )

    def test_old_stale_xyxy_not_used(self, scene):
        """blk.xyxy может быть устаревшим, но absBoundingRect возвращает правильные значения."""
        item = _make_flow_item(scene, xyxy=(100, 100, 300, 200))

        # Вручную установить устаревший xyxy (симуляция до исправления)
        item.blk.xyxy = [100, 100, 300, 200]

        # Переместить элемент
        old_pos = item.pos()
        item.setPos(QPointF(old_pos.x() + 200, old_pos.y() + 150))

        # absBoundingRect должен отражать перемещённую позицию
        bx, by, bw, bh = item.absBoundingRect()
        assert bx >= 290, (
            f"absBoundingRect x={bx} должен быть >= 290 после перемещения"
        )

        # Устаревший xyxy остался старым
        assert item.blk.xyxy == [100, 100, 300, 200]


# ── Интеграционные: перемещение + ресайз + OCR ────────────────

class TestCoordinateSyncIntegration:
    """End-to-end: перемещение, ресайз, затем проверка согласованности координат."""

    def test_move_then_flow_resize_xyxy_consistent(self, scene):
        """После перемещения и ресайза координаты согласованы."""
        from ui.textedit_commands import MoveBlkItemsCommand

        item = _make_flow_item(scene, xyxy=(100, 100, 300, 200))
        shape_ctrl = MagicMock()
        shape_ctrl.blk_item = item

        # Переместить
        old_pos = item.pos()
        item.setPos(QPointF(old_pos.x() + 100, old_pos.y() + 50))
        cmd = MoveBlkItemsCommand([item], shape_ctrl)
        cmd.redo()

        xyxy_after_move = list(item.blk.xyxy)

        # Затем ресайз через flow-хендлы
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(150, pt.y())
        item._update_flow_layout()

        xyxy_after_resize = list(item.blk.xyxy)

        # После ресайза ширина должна уменьшиться
        w_after_move = xyxy_after_move[2] - xyxy_after_move[0]
        w_after_resize = xyxy_after_resize[2] - xyxy_after_resize[0]
        assert w_after_resize < w_after_move, (
            f"Ширина должна уменьшиться: move={w_after_move} resize={w_after_resize}"
        )

        # Позиция y1 не изменилась (горизонтальный ресайз)
        assert xyxy_after_resize[1] == xyxy_after_move[1], (
            f"y1 изменился неожиданно: move={xyxy_after_move[1]} resize={xyxy_after_resize[1]}"
        )

    def test_undo_move_restores_xyxy_then_resize_works(self, scene):
        """После undo перемещения и последующего ресайза координаты корректны."""
        from ui.textedit_commands import MoveBlkItemsCommand

        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))
        shape_ctrl = MagicMock()
        shape_ctrl.blk_item = item

        original_xyxy = list(item.blk.xyxy)

        # Переместить
        old_pos = item.pos()
        item.setPos(QPointF(old_pos.x() + 100, old_pos.y() + 50))
        cmd = MoveBlkItemsCommand([item], shape_ctrl)
        cmd.redo()

        # Undo
        cmd.undo()

        # xyxy должен вернуться к исходному
        assert item.blk.xyxy == original_xyxy, (
            f"После undo: {item.blk.xyxy} != исходный {original_xyxy}"
        )

        # Теперь ресайз — должен работать корректно
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(200, pt.y())
        item._update_flow_layout()

        x1, y1, x2, y2 = item.blk.xyxy
        assert x2 - x1 <= 220, (
            f"После ресайза post-undo: ширина={x2 - x1} должна быть ~200"
        )


# ── Invariant-тесты: согласованность координат после каждой операции ──


def _assert_coords_consistent(item):
    """Проверить что blk.xyxy совпадает с absBoundingRect()."""
    bx, by, bw, bh = item.absBoundingRect()
    expected = [int(bx), int(by), int(bx + bw), int(by + bh)]
    assert item.blk.xyxy == expected, (
        f"blk.xyxy={item.blk.xyxy} != absBoundingRect={expected}"
    )


class TestCoordinateInvariant:
    """Invariant: после каждой операции blk.xyxy должен совпадать с absBoundingRect().

    Причина: координаты хранятся в трёх местах (xyxy, lines, _bounding_rect).
    Если какое-то место обновилось, а другое нет — invariant-тест поймает.
    """

    def test_invariant_after_move(self, scene):
        """После перемещения координаты согласованы."""
        from ui.textedit_commands import MoveBlkItemsCommand
        item = _make_flow_item(scene, xyxy=(100, 100, 300, 200))
        shape_ctrl = MagicMock()
        shape_ctrl.blk_item = item

        old_pos = item.pos()
        item.setPos(QPointF(old_pos.x() + 100, old_pos.y() + 50))
        cmd = MoveBlkItemsCommand([item], shape_ctrl)
        cmd.redo()
        _assert_coords_consistent(item)

    def test_invariant_after_undo_move(self, scene):
        """После undo перемещения координаты согласованы."""
        from ui.textedit_commands import MoveBlkItemsCommand
        item = _make_flow_item(scene, xyxy=(100, 100, 300, 200))
        shape_ctrl = MagicMock()
        shape_ctrl.blk_item = item

        old_pos = item.pos()
        item.setPos(QPointF(old_pos.x() + 100, old_pos.y() + 50))
        cmd = MoveBlkItemsCommand([item], shape_ctrl)
        cmd.redo()
        cmd.undo()
        _assert_coords_consistent(item)

    def test_invariant_after_flow_resize_right(self, scene):
        """После сужения правой границы координаты согласованы."""
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(200, pt.y())
        item._update_flow_layout()
        _assert_coords_consistent(item)

    def test_invariant_after_flow_resize_left(self, scene):
        """После сужения левой границы координаты согласованы."""
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))
        for i, pt in enumerate(item._left_points):
            item._left_points[i] = QPointF(80, pt.y())
        item._update_flow_layout()
        _assert_coords_consistent(item)

    def test_invariant_after_flow_resize_top(self, scene):
        """После смещения верхней границы вниз координаты согласованы."""
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))
        for i, pt in enumerate(item._left_points):
            item._left_points[i] = QPointF(pt.x(), pt.y() + 30)
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(pt.x(), pt.y() + 30)
        item._update_flow_layout()
        _assert_coords_consistent(item)

    def test_invariant_after_flow_resize_bottom(self, scene):
        """После смещения нижней границы вниз координаты согласованы."""
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))
        for i, pt in enumerate(item._left_points):
            item._left_points[i] = QPointF(pt.x(), pt.y() - 30)
        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(pt.x(), pt.y() - 30)
        item._update_flow_layout()
        _assert_coords_consistent(item)

    def test_invariant_after_move_then_resize(self, scene):
        """После перемещения и ресайза координаты согласованы."""
        from ui.textedit_commands import MoveBlkItemsCommand
        item = _make_flow_item(scene, xyxy=(100, 100, 300, 200))
        shape_ctrl = MagicMock()
        shape_ctrl.blk_item = item

        old_pos = item.pos()
        item.setPos(QPointF(old_pos.x() + 50, old_pos.y() + 30))
        cmd = MoveBlkItemsCommand([item], shape_ctrl)
        cmd.redo()

        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(150, pt.y())
        item._update_flow_layout()
        _assert_coords_consistent(item)

    def test_invariant_after_undo_then_resize(self, scene):
        """После undo перемещения и ресайза координаты согласованы."""
        from ui.textedit_commands import MoveBlkItemsCommand
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))
        shape_ctrl = MagicMock()
        shape_ctrl.blk_item = item

        old_pos = item.pos()
        item.setPos(QPointF(old_pos.x() + 100, old_pos.y() + 50))
        cmd = MoveBlkItemsCommand([item], shape_ctrl)
        cmd.redo()
        cmd.undo()

        for i, pt in enumerate(item._right_points):
            item._right_points[i] = QPointF(200, pt.y())
        item._update_flow_layout()
        _assert_coords_consistent(item)

    def test_invariant_update_textblk_list(self, scene):
        """После update_textblk_list координаты согласованы."""
        from ui.block_manager import BlockManager
        item = _make_flow_item(scene, xyxy=(0, 0, 400, 200))
        for i, pt in enumerate(item._left_points):
            item._left_points[i] = QPointF(80, pt.y())
        item._update_flow_layout()

        proj = MagicMock()
        cbl = []
        proj.current_block_list.return_value = cbl

        mgr = BlockManager.__new__(BlockManager)
        mgr.textblk_item_list = [item]
        mgr.pairwidget_list = [MagicMock()]
        mgr.pairwidget_list[0].e_source.toPlainText.return_value = "test"

        mgr.update_textblk_list(proj)
        saved_blk = cbl[0]
        # Координаты в сохранённом блоке совпадают с absBoundingRect
        bx, by, bw, bh = item.absBoundingRect()
        expected = [int(bx), int(by), int(bx + bw), int(by + bh)]
        assert saved_blk.xyxy == expected, (
            f"Сохранённый xyxy={saved_blk.xyxy} != expected={expected}"
        )
