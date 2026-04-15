# YouTube Heatmap Clipper — Professional Overhaul

## Planning
- [x] Read existing codebase
- [x] Write implementation plan
- [x] Get user approval

## Backend ([app.py](file://wsl.localhost/Ubuntu/home/ikay/workspace/yt-heatmap-clipper/app.py) + [run.py](file://wsl.localhost/Ubuntu/home/ikay/workspace/yt-heatmap-clipper/run.py))
- [x] Add API endpoint to fetch video metadata (title, channel, thumbnail, duration)
- [x] Add API endpoint for heatmap data
- [x] Add API endpoint for clip history (list + delete)
- [x] Support editable video title for output filename
- [x] Add subtitle style presets support in FFmpeg pipeline (modern, karaoke, minimal, bold, neon)
- [x] Add source tag style presets support in FFmpeg pipeline (classic, glass, minimal, neon)
- [x] Add video quality presets (high, medium, fast)
- [x] Add `blur_center` crop mode to web UI
- [x] Clip history manifest system

## Frontend ([templates/index.html](file://wsl.localhost/Ubuntu/home/ikay/workspace/yt-heatmap-clipper/templates/index.html))
- [x] Complete UI redesign with professional dark/light theme
- [x] Dark mode / Light mode toggle with smooth transitions
- [x] Subtitle design preset selector (visual previews)
- [x] Source tag design preset selector
- [x] Auto-fetch YouTube title on URL input (editable field)
- [x] Video detail/preview modal with embedded YouTube player
- [x] Animated gradient mesh background
- [x] Glassmorphism cards with backdrop-blur
- [x] Visual crop mode selector (icon cards)
- [x] Video quality preset selector
- [x] Professional typography (Google Fonts: Inter + JetBrains Mono)
- [x] Micro-animations and hover effects
- [x] Processing spinner overlay
- [x] Result cards with video player + download buttons

## Verification
- [/] Test dark/light mode toggle
- [ ] Test URL metadata fetch
- [ ] Test video preview modal
- [ ] Test clip generation with various presets
