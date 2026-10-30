# Hair V8 — primary volumes, temple UV and export consistency

> **Historical candidate review (2026-10-05).** Recorded build/browser results
> apply to this candidate and named checks only; they do not establish current
> likeness or full physics acceptance. See [STATE](STATE.md), [TODO](../TODO.md),
> and [documentation map](README.md).

2026-10-05. Separate candidate after [V7](CHARACTER_HAIR_V7_REVIEW.md), not the
active avatar or final likeness acceptance. Target remains the original
[turnaround/art direction](CHARACTER_ART_DIRECTION.md), without gloves.

## What changed and why

- Unequal broad relief and curved flow replace the completely smooth back;
  lower ends have a little more asymmetry. Three primary meshes, 13 spring
  chains / 39 weighted joints remain; no repeated strip meshes or dependency.
- Left front fall is broader and curved; opposite side is shorter/open.
  Upper roots are conformed to the cap and taper smoothly, removing the spike
  seen in the first V8 trial. This is still blocking, not strand detail.
- Read-only atlas/UV diagnostics localized the inherited maroon undercut to
  Face skin. Hard per-polygon material/UV replacements were visually rejected:
  they created rectangular skin patches. Final version smoothly remaps only
  lateral skin UV loops in the verified temple region, retaining the original
  shader and atlas. 176 polygons / 376 loops affected; eye/eyelash/iris material
  UV loops and all 56 face morphs are unchanged by this helper.
- Found and fixed a preview/export mismatch: `TextureInfo.image = None` was not
  a real RNA texture field. The builder now clears `index.source`, including
  inherited normal/emission/matcap/rim/outline textures on flat materials.
  Export asserts 12 palette materials are texture-free. Face/hand source
  textures remain intact. Existing V7 and other exported assets are unchanged;
  future rebuilds get the material API correction.

## Visual review

Same front/profile/back/3/4 cameras plus face/front/profile/quarter and crown
close-ups were inspected. Large maroon temple pigment and raised root spike
are removed. Back volume is less flat but still overly smooth; the front fall
still reads too much like one ribbon compared with the reference. Ear/skin
transition needs further close-up refinement. Shoulder cap, cargo fit and
boot detail remain inherited defects. Stage A and >=90 likeness are NOT accepted.
Do not add complex physics or fine strand decoration to conceal these shapes.

Previews: `runtime/character-reference/jawlie-hair-v8-rest-{front,profile,back,three-quarter}.png`
and `jawlie-hair-v8-{face,face-profile,face-quarter,crown-back}.png`.
Actual app screenshots: `runtime/character-reference/JawlieHairV8/`.

## Evidence

- Build: `build_vroid_reference.py -- --hair-sculpt-review --preview-fast`;
  Blender 5.2.1, `--python-exit-code 1`, final log
  `runtime/character-reference/hair-v8-build-20261005-r7.log`, exit 0.
  Failed/visually rejected r1-r5 are diagnostic history, not acceptance.
  Blender can return zero after a Python error without the explicit exit flag;
  an earlier r4 exit 0 did NOT establish successful export.
- VRM `runtime/vrm-models/JawlieHairV8.vrm`: 14,278,616 bytes;
  packed editable `runtime/character-reference/jawlie-hair-v8.blend`: 10,430,412 bytes.
  SHA256 `b21ce2934ffcd26f466ece92d1df6456f94c617147ac0c6d87e7c83d5bd0fc89`.
  38 exported meshes / 124 skeleton joints / 54 humanoid bones /
  504 primitive morph targets (not 504 independent expressions).
- Geometry run `0fc3316b2e484112bec9431ca022ba9d`, same SHA, exit 0:
  `runtime/character-reference/hair-v8-geometry.json`. Inherited boot manifold,
  wrist weights, connected bomber and two leg-flex clearance checks PASS.
  Face surface vs each of the three evaluated hair meshes: zero overlap pairs
  in rest. This does NOT establish all-pose collisions or hair/body clearance.
- Actual `/app` run `98e8fab7069c440c9c1a130407e409f6`, same SHA, exit 0:
  `runtime/character-reference/JawlieHairV8/validation.json`. One root,
  39 weighted native hair joints / 6 collider proxies; 7.0166 s / 241 frames,
  peak 0.45264 rad, finalRestDelta 0.0000446 rad, lateDrift 0.0003536 rad.
  Emotions/greeting/reduced motion/weighted helpers PASS.
  Headless SwiftShader, NOT hardware FPS or full cloth/soft-body acceptance.

## Coupled scene lifecycle slice

Code worker fixed restoration of additive motion on the old rig before ownership
changes. Real scene unload restores offsets and closes old `aa`; successful
handoff zeros lip target/speech state and new `aa`. Stale/failed loads retain
the current avatar/state. Non-finite lip values are rejected, finite values
clamped; idle/listening ignores late RMS samples. Playback generation fencing
remains with the existing audio owner. This is RMS-driven mouth opening, NOT
phoneme/vowel-aware lip-sync. Lifecycle tests are included in the full gate.

Next model slice: natural broad front/crown transitions and unequal back tips,
then relaxed shoulder cap and cargo silhouette. No active-avatar switch and
no claims of full production readiness were made.
