# Claude 배우기 — figure style (2026-10-20)

All lesson figures must look like one set. Start every file from the components in `figure-style-reference.svg` (same folder). SPEC §8a has the hard rules (SVG only, ≤ 60 KB, no scripts/foreignObject/external refs/raster).

## Canvas

- `viewBox="0 0 720 H"` with `width="720" height="H"`, H ideally 280–480. One plate: `<rect width="720" height="H" rx="16" fill="#f5f6f6"/>`.
- Outer margin 32. Gaps between blocks 24–40. Prefer fewer, bigger elements.
- No title inside the figure by default (the caption sits below it). Cover figures may carry one short heading (26px bold) when it helps.

## Type

- `font-family: 'Apple SD Gothic Neo', Pretendard, 'Noto Sans KR', sans-serif` via one `<style>` block with classes.
- Heading 26–30px bold · main label 20–24px semibold · secondary 18px `#6b7078` · never below 18px.
- Terminal text: `'SF Mono', Menlo, monospace` 18–20px, `#f7f8f8` on `#1d1d21`; prompts or highlights in `#a7b0ff`.
- Labels ≤ 12 words. Centre labels in cards with `text-anchor="middle"`. Check that no text overflows its box after rendering.

## Colour roles

| role | fill | stroke / text |
|---|---|---|
| plate | `#f5f6f6` | — |
| normal card | `#ffffff` | `#e4e4e8` 1.5px |
| focus card | `#e8eafb` | `#5e6ad2` 1.5px |
| success | `#e6f3e9` or white | `#1d8a38` 2px |
| caution | `#f8efdc` | `#a3720a` |
| danger / never | `#f8e3e1` | `#c4423b` |
| arrows, connectors | — | `#6b7078` 2px, marker arrowhead |
| numbered badge | `#5e6ad2` circle r=14 | white 17px bold number |
| terminal window | `#1d1d21` rx 12, three `#62666d` dots | mono text |
| screen sketch | white window, `#eceef0` top bar, `#e4e4e8` grey bars for text | target control outlined `#5e6ad2` 2px |

Use colour for meaning only: purple = where to look / what you do, green = done or OK, amber = careful, red = never. One focus colour per figure.

## Kinds

- **Flow**: 3–5 cards left→right (or top→bottom when labels are long), numbered badges, arrows between.
- **Concept map**: a centre card with 2–4 satellites, short connector labels.
- **Comparison**: two columns ("이렇게 하면" / "이렇게 하면 더 좋아요"), same height, the better side in the focus or success style. Never mark a side with ✗/✓ glyphs only; add words.
- **Screen sketch**: schematic window with grey bars; only the control that matters gets a real label (from FACTS.md) and a purple outline plus a numbered badge. Add a small `#6b7078` note "실제 화면은 조금 다를 수 있어요" when it shows a third-party screen. No logos, no brand marks, no copied UI.
- **Terminal sketch**: dark window, real commands only (from the lesson or FACTS.md), Korean side notes outside the window joined by thin connectors.
- **Decision chart**: question pills → answer cards; at most 3 levels.
- **Checklist card**: white card with 3–5 rows, each a small rounded square and a short line.

## Accessibility and accuracy

- Root `<svg ... role="img" aria-label="…">` matching the lesson's `alt`.
- Text in the figure must agree with the lesson text and FACTS.md. No invented numbers, prices or labels.
- Placeholders such as `{{가게이름}}` are not substituted inside images: use the example shop 햇살꽃집 or neutral words ("우리 가게").

## Self-check before handing in

1. `xmllint --noout file.svg` (or `/usr/bin/python3 -c "import xml.dom.minidom,sys;xml.dom.minidom.parse(sys.argv[1])" file.svg`).
2. Render: `qlmanage -t -s 1440 -o <scratchpad dir> file.svg` and look at the PNG. The PNG is square-padded; only the top part is the figure.
3. Check: no clipped or overlapping text, labels ≥ 18px, the main idea readable in 3 seconds, size ≤ 60 KB.
