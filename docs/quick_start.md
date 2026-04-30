# Quick Start

This guide shows the fastest way to create a video with subtitles burned into the picture.

## 1. Open Smart Subtitle

Run the program with:

```text
python main.py
```

The main window is divided into three work areas:

- Left panel: video and subtitle input.
- Center workspace: preview and subtitle editor.
- Right panel: subtitle style and output.

Use **View > Reset Layout** if the workspace looks different from the default layout.

## 2. Load a Video

1. Open **1. Video Input**.
2. Click **Select Video**.
3. Choose your video file.
4. Check that the video information appears, including width, height, duration, aspect ratio, and orientation.

If the video does not load, make sure FFmpeg is installed and the file is not damaged.

## 3. Load Subtitles

1. Open **2. Subtitle Input**.
2. Click **Select Subtitle**.
3. Choose a subtitle file.

Supported formats:

- SRT
- VTT
- TXT
- CSV
- JSON

Click **Parse / Preview** if you need to reload or check the subtitle file after changing import settings.

## 4. Check the Preview

The **Preview** panel shows the video and subtitle overlay.

Use the preview controls to:

- Play or pause the video.
- Move through the video with the timeline slider.
- Change preview zoom with **Fit**, **10%**, **20%**, **25%**, **50%**, **75%**, **100%**, **125%**, **150%**, or **200%**.
- Open a larger preview with **Full**.
- Use **Render Preview Video** when you need to check the result through the same FFmpeg rendering path used for export.

Important: preview zoom changes how large the preview looks on screen. It does not change the final exported subtitle size.

## 5. Edit Subtitle Text and Timing

Use the **Subtitle Editor** table to select a subtitle cue.

For the selected cue:

1. Edit **Start**, **End**, or **Duration** in **Selected Cue Timing**.
2. Click **Set Start = Current** or **Set End = Current** to use the current preview time.
3. Edit the text in **Subtitle text / manual line breaks**.
4. Click **Apply Text** or **Apply Timing**.

You can also use:

- **Add** to insert a cue.
- **Delete** to remove selected cues.
- **Split** to split a cue at the current preview time.
- **Merge Prev** or **Merge Next** to combine cues.
- **Auto Arrange** to re-wrap text and check that subtitles fit inside the video frame.

## 6. Auto Sync Speech, If Needed

If you already have clean subtitle text and want the app to align it to the spoken audio:

1. Open **2. Subtitle Input**.
2. Keep **Preserve existing subtitle text** enabled.
3. Choose the speech model and language.
4. Click **Auto Speech Sync**.

For best text quality, treat your existing subtitle text as the source of truth. Auto sync should align it to speech, not replace it with rough speech recognition text.

## 7. Style the Subtitles

Open **3. Global Subtitle Style**.

Common settings:

- **Preset**: quick starting styles such as Clean, TikTok, Documentary, or YouTube.
- **Font family** and **Font size**.
- **Text color**.
- **Stroke** on/off, color, and width.
- **Shadow** on/off and strength.
- **Background box** on/off, color, and opacity.
- **Max width** and **Max lines**.
- **Position** and bottom/safe-area settings.

After changing **Max width** or **Max lines**, click **Auto Arrange** in the Subtitle Editor to re-wrap subtitle text.

## 8. Export the Finished Video

1. Open **4. Output**.
2. Click **Save As** and choose an output `.mp4` path.
3. Click **Generate Subtitle Video**.
4. Watch the progress bar and log messages.

The exported video will contain hard subtitles burned into the video image.

You can also click **Export Edited Subtitle** to save the edited subtitle file separately.

