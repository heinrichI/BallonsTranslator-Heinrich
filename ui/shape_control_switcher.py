"""
Delegating proxy that switches between the two text-block shape controls:

- FlowShapeControl   -> FlowTextBlkItem (flow boundary handles)
- TextBlkShapeControl -> TextBlkItem     (legacy 8-handle resize/rotate)

canvas.txtblkShapeControl is replaced by a ShapeControlSwitcher so every
existing call site (canvas.py, scenetext_manager.py, mainwindow.py,
textedit_commands.py) keeps working unchanged; setBlkItem picks the correct
control for the block type and everything else delegates to the active one.
"""


class ShapeControlSwitcher:
    """Delegates to the active shape control; switches by block type on setBlkItem."""

    def __init__(self, flow_ctrl, legacy_ctrl, canvas):
        self._flow_ctrl = flow_ctrl
        self._legacy_ctrl = legacy_ctrl
        self._canvas = canvas
        self._active = flow_ctrl  # new blocks default to flow mode

    def setBlkItem(self, blk_item):
        from ui.flow_textitem import FlowTextBlkItem  # lazy import avoids cycles

        if blk_item is None:
            self._active.setBlkItem(None)
            return
        target = self._flow_ctrl if isinstance(blk_item, FlowTextBlkItem) else self._legacy_ctrl
        if target is not self._active:
            # Release the old item/control before switching.
            self._active.setBlkItem(None)
            self._active.hide()
            self._active = target
            self._active.updateScale(getattr(self._canvas, 'scale_factor', 1.0))
        self._active.setBlkItem(blk_item)

    def __getattr__(self, name):
        return getattr(self._active, name)
