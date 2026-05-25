# Progress

## What Works
- HF ogkalu detector integrated and auto-registered as `comic-text-and-bubble-detector`.
- CTD-based refinemask integration in detectors: `refine_mask(img, coarse_mask, blk_list)` returns per-character masks when blk_list aligns to text lines.
- Debug tooling: scripts to run detector and compare masks.
- Russian comments added to CTD detector and CTD basemodel/inference files for maintainability.

## What's Left
- Split large merged blocks into lines before calling `refine_mask` to obtain character-level masks instead of block masks.
- Unit tests to cover HF parsing helpers and large-block split logic.
- UI exposure: surface `box_padding` and `mask dilate size` more prominently and consider safer defaults (0/0) for new users.
- Documentation: update doc/modules and CHANGELOG with the detector changes.

## Current Status
- Implemented defensive parsing, padding/clamping, merge protection.
- Added debug scripts and mask diagnostics.
- Added localised comments in CTD-related modules.

## Next Milestones
- [ ] Implement splitting of oversized merged blocks into lines and re-run diagnostics.
- [ ] Add unit tests for `_safe_box_from_item` and split logic.
- [ ] Manual UI verification with multiple comic pages.
- [ ] Update doc/modules and CHANGELOG.