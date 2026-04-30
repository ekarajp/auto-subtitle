# Smart Subtitle User Manual

Smart Subtitle is a desktop application for preparing subtitles and exporting a finished video with subtitles burned into the picture. It is designed for people who need to load a video, import subtitle text, fix timing, adjust subtitle style, preview the result, and export a final video.

This manual is written for beginners. You do not need to know video editing terms before using the program.

## 1. What Smart Subtitle Does

Smart Subtitle helps you:

- Load a video.
- Import subtitles from SRT, VTT, TXT, CSV, or JSON.
- Edit subtitle text and timing.
- Sync existing subtitle text to spoken audio.
- Automatically arrange text so it fits inside the video frame.
- Change subtitle style, font, color, stroke, shadow, and background.
- Preview the result before export.
- Export a new video with subtitles burned in.
- Export the edited subtitle file for use on other platforms.

The main workflow is:

1. Load video.
2. Load or create subtitles.
3. Check timing and text.
4. Style the subtitles.
5. Preview.
6. Export.

## 2. Opening the Program

Open a terminal or command prompt in the project folder and run:

```text
python main.py
```

If the app does not open, check that Python, PySide6, and FFmpeg are installed. See **Troubleshooting / FAQ** for common setup problems.

## 3. Main Window Overview

The application window has several main areas.

### Top Toolbar

The top toolbar contains quick layout controls:

- **Left**: show or hide the left settings panel.
- **Right**: show or hide the right settings panel.
- **Focus Preview**: hide nonessential panels so the Preview becomes the main focus.
- **Reset**: restore the standard workspace layout.

These controls only change the workspace layout. They do not change your subtitle data.

### Left Panel

The left panel contains input controls:

- **1. Video Input**
- **2. Subtitle Input**

Each section can be collapsed or expanded. Collapse sections when you need more workspace area.

### Center Workspace

The center workspace contains:

- **Preview**
- **Subtitle Editor**

This is where most editing work happens.

### Right Panel

The right panel contains:

- **3. Global Subtitle Style**
- **4. Output**
- **5. Selected Subtitle Manual Style**

Use this panel for visual styling, export settings, and special per-subtitle style overrides.

## 4. Video Input

Use **1. Video Input** to load the video you want to subtitle.

Click **Select Video** and choose a video file. After loading, the app reads video information such as:

- Width and height.
- FPS.
- Duration.
- Aspect ratio.
- Orientation, such as landscape, portrait, square, or other.

The app uses this information to place subtitles in a safer position for the actual video size. For example, vertical videos get a larger bottom safety margin than standard landscape videos.

## 5. Subtitle Input

Use **2. Subtitle Input** to load subtitle text.

Supported formats:

- **SRT**: standard subtitle file with numbered cues and timecodes.
- **VTT**: web subtitle file.
- **TXT**: plain text or timestamped text.
- **CSV**: rows with `start`, `end`, and `text`.
- **JSON**: an array of objects with `start`, `end`, and `text`.

### TXT Modes

TXT files can be used in two ways.

Plain text mode:

- One line becomes one subtitle cue.
- If the text has no timestamps, the app can distribute cues across the video or use a duration per line.

Timestamped text mode:

```text
00:00:01.000 --> 00:00:03.500|Hello world
```

The part before `|` is the time range. The part after `|` is the subtitle text.

### CSV Format

CSV files should contain:

```text
start,end,text
00:00:01.000,00:00:03.000,Hello world
```

### JSON Format

JSON files should look like this:

```json
[
  {"start": "00:00:01.000", "end": "00:00:03.000", "text": "Hello"},
  {"start": "00:00:04.000", "end": "00:00:06.000", "text": "World"}
]
```

## 6. Speech Sync

Speech sync listens to the video audio and tries to align subtitles to the spoken words.

Use speech sync when:

- You already have subtitle text, but the timing is wrong.
- You have a transcript and want the app to place it on the timeline.

Recommended beginner setting:

- Keep **Preserve existing subtitle text** enabled.

This tells the app to treat your subtitle text as the source of truth. Speech recognition is used as an alignment guide, not as a replacement for your clean text.

Speech sync may take time, especially with large models or long videos. GPU mode can be faster if your system supports it.

## 7. Preview

The **Preview** panel shows what your subtitles look like on the video.

The preview has two different concepts:

- **Preview area size**: how much screen space the Preview panel gets in the app layout.
- **Preview zoom**: how large the video appears inside the Preview panel.

These are not the same.

If the Preview panel is too small, drag splitters or hide side panels. If the video image inside the Preview is too small or too large, change the zoom level.

### Preview Zoom

Available zoom levels:

- Fit
- 10%
- 20%
- 25%
- 50%
- 75%
- 100%
- 125%
- 150%
- 200%

**Fit** scales the video to fit inside the available preview viewport while preserving aspect ratio.

Manual zoom levels can be larger than the viewport. When that happens, scrollbars appear so you can pan around the preview.

### Full Preview

Use **Full** when you want a larger preview window. The full preview includes playback controls so you can check the result more comfortably.

### Render Preview Video

Normal preview is designed to be fast. **Render Preview Video** creates a temporary rendered preview using FFmpeg/libass, closer to the final export path. Use it when you want to confirm exact export behavior before rendering the full video.

## 8. Subtitle Editor

The **Subtitle Editor** is where you review, edit, add, delete, split, and merge subtitle cues.

Each row shows:

- Index number.
- Start time.
- End time.
- Duration.
- Subtitle text.

Select a row to edit it. The selected subtitle appears in the preview at its time position.

### Editing Text

Use **Subtitle text / manual line breaks** to edit the selected subtitle.

Press Enter to add a manual line break. Manual line breaks are useful when you want to control exactly how the subtitle is split across lines.

Click **Apply Text** after editing.

### Editing Timing

Use **Selected Cue Timing** to edit:

- Start time.
- End time.
- Duration.

Click **Apply Timing** after changing timing fields.

### Set Start and End from Current Time

The current time comes from the preview playhead.

- **Set Start = Current** sets the selected subtitle start time to the current preview time.
- **Set End = Current** sets the selected subtitle end time to the current preview time.

This is useful when playing or scrubbing the video and marking the exact moment where a subtitle should appear or disappear.

### Nudge Controls

Use **Nudge...** for small timing changes:

- Move the whole cue earlier or later.
- Adjust only the start time.
- Adjust only the end time.

This is helpful for fine corrections, such as moving a subtitle by 0.1 seconds.

### Split and Merge

Use **Split** to divide a selected subtitle at the current preview time.

Use **Merge Prev** or **Merge Next** to combine the selected cue with a neighbor.

## 9. Auto Arrange Text

Use **Auto Arrange** after editing text, changing font size, changing maximum width, or changing maximum lines.

Auto Arrange tries to:

- Keep subtitles within the safe visible area.
- Avoid text falling outside the video frame.
- Use the configured maximum number of lines.
- Prefer natural line breaks.
- Avoid splitting Thai words in the middle.

Default beginner recommendation:

- Keep **Max lines** at 2.
- Use **Auto Arrange** after changing **Max width**.

If a subtitle still looks too crowded, split it into two cues or shorten the text.

## 10. Global Subtitle Style

Use **3. Global Subtitle Style** to control the default look of all subtitles.

Common settings:

- **Preset**: choose a quick style such as Clean, TikTok, Documentary, or YouTube.
- **Font family**: choose the subtitle font.
- **Font size**: change subtitle size.
- **Text color**: choose main text color.
- **Stroke**: add or remove outline around text.
- **Stroke color** and **Stroke width**: control outline appearance.
- **Shadow**: add depth and contrast.
- **Background box**: place a colored box behind text.
- **Background opacity**: control how transparent the box is.
- **Alignment**: set text alignment.
- **Safe area** and margins: keep text away from video edges.
- **Max width**: limit how wide subtitle lines can be.
- **Max lines**: limit how many lines a cue can use.
- **Text position**: choose automatic or custom placement.

### Global Style vs Selected Subtitle Manual Style

Global style affects all subtitles.

Selected Subtitle Manual Style affects only the currently selected subtitle, and only when manual override is enabled. Use manual style for special cases, not for normal global formatting.

## 11. Output

Use **4. Output** to export your work.

### Generate Subtitle Video

This creates a new video file with subtitles burned into the image. The result is a hard-subtitled video.

Steps:

1. Click **Save As**.
2. Choose an output `.mp4` path.
3. Click **Generate Subtitle Video**.
4. Watch the progress bar and log window.

### Export Edited Subtitle

This saves the edited subtitle file separately. Use this when you want to upload subtitles to YouTube, social platforms, or another editing program.

### Render Preview Video

This creates a temporary preview render using the same rendering path as final export. It is useful when you want to compare the real render with the normal interactive preview.

## 12. Panel and Layout Controls

Use the **View** menu or top toolbar:

- **Toggle Left Panel**: show or hide the left panel.
- **Toggle Right Panel**: show or hide the right panel.
- **Toggle Focus Preview**: make the Preview the main focus.
- **Reset Layout**: restore the normal workspace.

Collapsible sections can be opened or closed individually. Collapsing a section frees space for other work areas.

## 13. Common Beginner Tasks

### Load a Video

1. Open **1. Video Input**.
2. Click **Select Video**.
3. Choose the video.
4. Confirm that video information appears.

### Add Subtitle Text

1. Load a subtitle file in **2. Subtitle Input**, or use **Add** in the Subtitle Editor.
2. Select a cue.
3. Type the text in **Subtitle text / manual line breaks**.
4. Click **Apply Text**.

### Change Font and Size

1. Open **3. Global Subtitle Style**.
2. Choose **Font family**.
3. Change **Font size**.
4. Watch the Preview update.
5. Click **Auto Arrange** if text wrapping needs to be recalculated.

### Move a Subtitle Earlier or Later

1. Select a subtitle row.
2. Use **Nudge...**.
3. Choose a move option, such as earlier 0.1 seconds or later 0.1 seconds.

### Set Start and End from the Preview Time

1. Play or scrub the video to the desired time.
2. Select the subtitle cue.
3. Click **Set Start = Current** or **Set End = Current**.
4. Click **Apply Timing** if needed.

### Make Preview Larger

Options:

- Hide the left or right panel.
- Use **Focus Preview**.
- Drag splitters to give the Preview more space.
- Change preview zoom to **Fit**.
- Open **Full** preview.

## 14. Best Practices

- Keep subtitles short enough to read comfortably.
- Use two lines or fewer for most subtitles.
- Do not place subtitles too close to the video edge.
- Use stroke or shadow when text is hard to read.
- Use **Render Preview Video** before final export when exact output matters.
- Keep **Preserve existing subtitle text** enabled when syncing a clean transcript.
- Use **Auto Arrange** after changing max width, font size, or max lines.
- Export the edited subtitle file as a backup before major changes.

