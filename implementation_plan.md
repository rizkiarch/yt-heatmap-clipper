# YouTube Heatmap Clipper — Professional Overhaul

Redesign the entire web application to be premium and professional. Current UI is a basic form with minimal styling. The overhaul includes: professional subtitle FFmpeg styles, dark/light mode, design preset selectors, auto-fetched editable YouTube titles, and a video detail modal with player + transcript viewer.

## Proposed Changes

### Backend API  

#### [MODIFY] [app.py](file:///wsl.localhost/Ubuntu/home/ikay/workspace/yt-heatmap-clipper/app.py)

**New API Endpoints:**

| # | Endpoint | Purpose |
|---|----------|---------|
| 1 | `GET /api/video-info?url=...` | Fetch metadata (title, channel, thumbnail, duration, view count) via yt-dlp |
| 2 | `POST /api/transcript` | Generate transcript preview from video segment via Faster-Whisper |
| 3 | `GET /api/heatmap?url=...` | Return heatmap data as JSON for visual timeline graph in the UI |
| 4 | `GET /api/history` | List previously generated clips with metadata (title, date, duration, file size) |
| 5 | `DELETE /api/history/<filename>` | Delete a specific generated clip |

**Updated `POST /` route — new form fields:**
- `video_title` — Editable output filename (sanitized from YouTube title)
- `subtitle_style` — Preset name (`modern`, `karaoke`, `minimal`, `bold`, `neon`)
- `source_style` — Preset name (`glass`, `minimal`, `neon`, `classic`)
- `use_source_tag` — Toggle for source tag overlay
- `source_interval` — Animation interval seconds
- `video_quality` — Output quality preset (`high` 1080p/crf18, `medium` 720p/crf23, `fast` 720p/crf28)

**Additional Backend Features:**
- **Smart filename** — Auto-generate from YouTube title (sanitized), user can edit before processing
- **Clip history with JSON manifest** — Save `clips/manifest.json` tracking all generated clips with metadata (source URL, title, timestamp, duration, file size, presets used)
- **Heatmap visualization data** — Return normalized heatmap scores so frontend can render an interactive timeline chart showing engagement peaks
- **Video quality selector** — Let user choose between High/Medium/Fast quality presets that map to FFmpeg CRF + resolution settings

---

### Subtitle & Source Tag Presets

#### [MODIFY] [run.py](file:///wsl.localhost/Ubuntu/home/ikay/workspace/yt-heatmap-clipper/run.py)

1. **Subtitle style presets** — Add a dict `SUBTITLE_STYLES` with 5 presets, each defining FFmpeg `force_style` parameters:
   - `modern` — Clean white text, thin outline, no background box, bottom-center
   - `karaoke` — Word-by-word highlight effect with yellow active word
   - `minimal` — Small font, slight shadow, no outline, bottom-left aligned
   - `bold` — Large thick text, heavy black outline, centered
   - `neon` — Glowing effect with colored outline + shadow, centered

2. **Source tag style presets** — Add a dict `SOURCE_TAG_STYLES` with 4 presets:
   - `glass` — Semi-transparent glass panel, blur effect
   - `minimal` — Text-only with subtle shadow (no background box)
   - `neon` — Glowing colored border + text
   - `classic` — Current design (black box with red accent)

3. **Update [proses_satu_clip()](file://wsl.localhost/Ubuntu/home/ikay/workspace/yt-heatmap-clipper/run.py#573-854)** — Accept `subtitle_style` and `source_style` params, apply the correct FFmpeg filter based on preset selection. Remove the hardcoded background-color-based subtitle.

4. **Update [build_source_tag_filter()](file://wsl.localhost/Ubuntu/home/ikay/workspace/yt-heatmap-clipper/run.py#500-526)** — Accept a `style` parameter and build the appropriate FFmpeg drawtext/drawbox filter for each preset.

---

### Frontend Complete Redesign

#### [MODIFY] [index.html](file:///wsl.localhost/Ubuntu/home/ikay/workspace/yt-heatmap-clipper/templates/index.html)

Complete rewrite with professional UI/UX:

**Theme System:**
- CSS custom properties for dark and light palettes
- Toggle button with smooth transition (icon: sun/moon)
- Persist preference in `localStorage`
- Dark: deep navy/charcoal backgrounds, soft white text
- Light: clean white backgrounds, dark text

**Layout:**
- Full-viewport gradient background with animated mesh
- Glass-morphism panels with backdrop-blur
- Three-column card layout for preset selectors
- Responsive grid with `min()` / [clamp()](file://wsl.localhost/Ubuntu/home/ikay/workspace/yt-heatmap-clipper/run.py#27-36) sizing

**Form Redesign:**
- YouTube URL input with animated floating label
- On URL blur/enter: auto-fetch video info via `/api/video-info`
- Display thumbnail + channel name + duration chip
- Editable title field pre-filled from YouTube title
- Crop mode selector with visual icon cards (not a dropdown)
- Subtitle style preset selector — visual preview cards showing how each style looks
- Source tag style preset selector — visual preview cards
- Source tag toggle switch (modern toggle, not checkbox)
- Source tag interval slider with live value display
- Enable subtitle toggle switch

**Video Preview Modal:**
- Triggered by "Preview" button after URL is entered
- Embedded YouTube iframe player
- Editable title field
- "View Transcript" button opens scrollable transcript panel
- Transcript fetched from `/api/transcript` with loading spinner
- Close button + ESC key + click-outside-to-close

**Processing Feedback:**
- Animated progress indicator during processing
- Real-time log viewer with syntax-highlighted output
- Success/error states with animations

**Results Section:**
- Video player cards for each generated clip
- Download button + filename display
- SRT subtitle file download link (if available)

**Typography & Animations:**
- Google Fonts: Inter (body), JetBrains Mono (logs)
- Micro-animations: button hover scales, input focus glow, card hover lift
- Animated gradient text for headings
- Smooth page transitions

---

## Verification Plan

### Browser Testing
1. Start the Flask dev server:
   ```bash
   cd /home/ikay/workspace/yt-heatmap-clipper && source venv/bin/activate && python app.py
   ```
2. Open `http://127.0.0.1:5000` in browser
3. Verify:
   - Dark/light mode toggle works and persists on reload
   - Paste a YouTube URL → video info auto-fetches (title, thumbnail, channel)
   - Title field is editable
   - Click "Preview" → modal opens with embedded player
   - Click "View Transcript" in modal → transcript loads
   - Select different subtitle/source presets → visual cards highlight correctly
   - Submit form → loading animation appears
   - After processing → result clips displayed with player and download buttons

### Manual Testing
- Process a real YouTube video with different subtitle style presets and verify the FFmpeg output has the correct styling (no background boxes, professional text rendering)
- Verify output filename matches the edited title
- Test mobile responsiveness by resizing browser
