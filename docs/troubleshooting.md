# Troubleshooting / FAQ

This page explains common beginner problems and how to fix them.

## The App Opens, But Video Does Not Load

Try these checks:

1. Make sure the video file exists and is not still downloading.
2. Try a common file type such as `.mp4`.
3. Install FFmpeg and make sure `ffmpeg` and `ffprobe` are available from the command line.
4. Check the log window in **4. Output** for a readable error message.

## FFmpeg Is Missing

Smart Subtitle uses FFmpeg to read video metadata, render preview videos, and export final videos.

Install FFmpeg, then restart the app. On Windows, you can install FFmpeg with a package manager or download it from the official FFmpeg website. After installation, make sure the FFmpeg `bin` folder is in your system PATH.

To test, open a terminal and run:

```text
ffmpeg -version
ffprobe -version
```

Both commands should print version information.

## Subtitles Do Not Appear in Preview

Check:

1. A video is loaded.
2. A subtitle file is loaded and parsed.
3. The current preview time is inside the selected subtitle start/end time.
4. The subtitle text is not empty.
5. Text color is not the same as the video background.
6. Subtitle position is not outside the frame.

Try selecting a subtitle row and clicking **Preview**.

## Preview Is Too Small

There are two separate controls:

- Workspace size: drag panels and splitters, hide side panels, or use **Focus Preview**.
- Preview zoom: use the zoom dropdown inside Preview.

Use **Fit** if the video does not fit in the preview viewport.

## Preview Is Too Large and Scrollbars Appear

This is normal when using manual zoom levels such as 100%, 150%, or 200%. Scrollbars let you pan around the preview.

Choose **Fit** if you want the whole video visible.

## Text Is Too Long or Falls Outside the Frame

Try:

1. Open **3. Global Subtitle Style**.
2. Reduce **Font size**.
3. Increase **Max width** if there is enough room.
4. Keep **Max lines** at 2 for normal subtitles.
5. Click **Auto Arrange** in the Subtitle Editor.
6. Split very long cues into shorter cues.

For Thai text, Auto Arrange tries to avoid breaking words in unnatural places. If a line still looks awkward, add a manual line break in the selected text editor.

## Export Does Not Look Exactly Like Preview

Normal preview is designed for speed. Final export uses FFmpeg/libass.

For the closest check before full export:

1. Click **Render Preview Video**.
2. Review the rendered preview.
3. Adjust style or layout if needed.
4. Export the final video.

If subtitle size or position looks wrong, check font size, max width, safe area, margins, and selected subtitle manual style overrides.

## Panels Disappeared

You may have hidden panels or enabled Focus Preview.

Try:

- Click **Left** or **Right** in the top toolbar.
- Use **View > Toggle Left Panel**.
- Use **View > Toggle Right Panel**.
- Use **View > Reset Layout**.

## Speech Sync Changes Text Too Much

For best results when you already have clean text:

1. Keep **Preserve existing subtitle text** enabled.
2. Use speech sync as an alignment tool, not a text rewriting tool.
3. Review the output after syncing.
4. Use **Auto Arrange** after syncing.

If the result is still poor, try a stronger speech model or manually correct the affected cues.

## Speech Sync Is Slow

Large speech models are slower but can be more accurate. Long videos also take more time.

Try:

- Use a smaller model for quick drafts.
- Use GPU compute if your system supports it.
- Test on a short section first.

## Timing Edits Do Not Match What I Expected

Remember:

- Preview current time is where the playhead is now.
- Subtitle start time is when the selected cue appears.
- Subtitle end time is when the selected cue disappears.
- Duration is end time minus start time.

Use **Set Start = Current** and **Set End = Current** when you want exact timing from the preview playhead.

## I Changed Max Width, But Text Did Not Re-Wrap

After changing **Max width** or **Max lines**, click **Auto Arrange** in the Subtitle Editor. This recalculates line breaks for the subtitles.

