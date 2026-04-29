# Implementation Plan

[Overview]
Fix context menu behavior: menu should only appear when right-clicking on a text block. Add "Add point to left" and "Add point to right" options to the standard context menu for all text blocks.

[Types]
No type changes required.

[Files]
### Existing files to be modified:

**ui/canvas.py**
- Lines 692-708: Simplify mouseReleaseEvent right-click handling - only call on_create_contextmenu when clicked on a TextBlkItem (including FlowTextBlkItem), otherwise do nothing
- Lines 770+: Restore `on_create_contextmenu` method with full original menu + new flow options

**ui/textitem.py** (or ui/flow_textitem.py if adding point logic there)
- Add logic to handle "Add point" menu actions

[Functions]
- **Modified: Canvas.mouseReleaseEvent** (ui/canvas.py, ~line 692)
  - Change: When right-click detected on TextBlkItem, call on_create_contextmenu
  - When right-click on empty canvas, do nothing
  
- **Restored: Canvas.on_create_contextmenu** (ui/canvas.py, ~line 770)
  - Original menu items: Copy, Paste, Delete, Copy source text, Paste source text, Delete and Recover removed text, Apply font formatting, Auto layout, Reset Angle, Squeeze, Save PNG, translate, OCR, OCR and translate, OCR translate and inpaint, inpaint
  - New: Add flow-specific section at end:
    - "Добавить точку слева" (Add point to left)
    - "Добавить точку справа" (Add point to right)
  - These options only work if the clicked item is a FlowTextBlkItem

- **New: Helper to get clicked text item**
  - In on_create_contextmenu, determine which text item was clicked and store reference
  - Pass to action handlers for "Add point" actions

[Classes]
No class changes required.

[Dependencies]
No new dependencies.

[Testing]
- Right-click on empty canvas: no menu should appear
- Right-click on any TextBlkItem: full menu with add point options
- "Add point to left/right" adds a point at click Y position

[Implementation Order]
1. Restore on_create_contextmenu method with full original menu from commit 8796ac8
2. Simplify mouseReleaseEvent to only call on_create_contextmenu for TextBlkItem clicks
3. Add "Add point" menu items and handler logic
4. Test context menu appears only on text blocks
