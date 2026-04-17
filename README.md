# Smart Subtitle

Desktop app สำหรับฝัง subtitle ลงในวิดีโอบน Windows โดยใช้ Python, PySide6 และ FFmpeg

## ความสามารถหลัก

- เลือกไฟล์วิดีโอ และอ่าน metadata ด้วย `ffprobe`
- รองรับ subtitle format: `TXT`, `SRT`, `VTT`, `CSV`, `JSON`
- ตั้งค่า font, size, color, stroke, shadow, background box, opacity, alignment, margin, safe area, line spacing, max width และตำแหน่งข้อความ
- เปิด/ปิด stroke ได้ เลือกสี stroke และปรับความหนา stroke ได้
- ตรวจ orientation และ aspect ratio อัตโนมัติ เช่น `16:9`, `9:16`, `1:1`
- แปลง subtitle เป็น ASS ภายในเพื่อควบคุม style แล้ว render ด้วย FFmpeg
- Preview วิดีโอจริงก่อน export พร้อม subtitle overlay ตามเวลา playback
- ปุ่ม `Full Preview` สำหรับดู preview แบบเต็มจอ กด `Esc` เพื่อออก
- Full Preview จะ pause preview หลักก่อนเปิด เพื่อไม่ให้เสียงวิดีโอซ้อนกัน
- เปิดโปรแกรมแบบ maximized เป็นค่าเริ่มต้น เพื่อให้เห็นคำสั่งหลักครบมากขึ้น
- มี progress bar และ log ระหว่าง export
- Save/Load project config เป็น JSON
- Export subtitle ที่แก้แล้วแยกออกมาเป็น `SRT`, `VTT`, `ASS`, `JSON`, `CSV`, หรือ timestamped `TXT`
- รองรับภาษาไทยและอังกฤษด้วย UTF-8
- แก้ subtitle ก่อน export ได้: แก้คำพูด, แก้เวลาเริ่ม/จบ, เพิ่มแถว, ลบแถว และ preview แถวที่เลือก
- แก้ข้อความหลายบรรทัดได้ในช่อง `Selected subtitle text / line breaks`
- ปุ่ม `Auto Arrange Text` ช่วยจัด subtitle ยาวให้ไม่เกิน `Max lines` และแตกเป็น subtitle ใหม่ถ้าจำเป็น
- Auto Timing Cleanup ใช้ FFmpeg `silencedetect` ช่วยหาช่วงเงียบ แล้วตัด subtitle หลังหยุดพูดตามค่า hold ที่ตั้งไว้

## โครงสร้างโปรเจกต์

```text
Smart Subtitle/
├─ main.py
├─ requirements.txt
├─ README.md
├─ core/
│  ├─ video_info.py        # อ่าน metadata ด้วย ffprobe
│  ├─ subtitle_models.py   # dataclass ของ subtitle cue/document
│  ├─ subtitle_parser.py   # parser สำหรับ TXT/SRT/VTT/CSV/JSON
│  ├─ style_preset.py      # style model, preset, safe area logic
│  ├─ ass_builder.py       # สร้าง ASS subtitle พร้อม layout อัตโนมัติ
│  ├─ renderer.py          # เรียก FFmpeg และอ่าน progress
│  └─ project_config.py    # save/load config
├─ ui/
│  ├─ main_window.py       # PySide6 main UI
│  ├─ preview_widget.py    # mock preview canvas
│  └─ render_worker.py     # worker thread สำหรับ export
└─ utils/
   └─ timecode.py          # parse/format timecode
```

## ติดตั้ง

ต้องใช้ Python 3.11 ขึ้นไป

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Optional Auto Speech Sync

`Auto Speech Sync` listens to the video audio with Whisper and creates subtitle cues from word timestamps. This is optional because it may download a model and needs more CPU/GPU resources than normal subtitle editing.

Install it only when needed:

```powershell
pip install faster-whisper
```

How to use:

1. Select a video.
2. Choose `Speech model`. `large-v3` is the default for maximum quality. `large-v3-turbo` is usually faster with very high quality.
3. Choose language, or keep `Auto language`.
4. Choose compute type. Use `float16` on CUDA GPU, `int8_float16` when you need lower VRAM, or `auto` if unsure.
5. Use `Beam 5` or higher for quality. Higher values can be slower.
6. Click `Auto Speech Sync`.
7. Review and edit the generated subtitle table before export.

Notes:

- The first run may take longer because the Whisper model may download.
- This creates a synced draft from detected speech. For final quality, review names, technical terms, punctuation, and Thai word spacing manually.
- The generated cues are cut for subtitle readability: short pauses, punctuation, max 1-2 lines, reading speed, and cue duration are all considered.
- Existing subtitle import/edit/export still works without `faster-whisper`.

## ติดตั้ง FFmpeg บน Windows

วิธีง่ายด้วย Winget:

```powershell
winget install Gyan.FFmpeg
```

หรือดาวน์โหลดจาก:

- https://www.gyan.dev/ffmpeg/builds/
- แตกไฟล์ แล้วเพิ่มโฟลเดอร์ `bin` เช่น `C:\ffmpeg\bin` ลงใน Environment Variable `PATH`

ตรวจสอบ:

```powershell
ffmpeg -version
ffprobe -version
```

## วิธีรัน

```powershell
python main.py
```

## รูปแบบ Subtitle ที่รองรับ

### SRT

```srt
1
00:00:01,000 --> 00:00:03,500
สวัสดีครับ

2
00:00:04,000 --> 00:00:06,000
Hello world
```

### VTT

```vtt
WEBVTT

00:00:01.000 --> 00:00:03.500
สวัสดีครับ
```

### TXT แบบ timestamped

```text
00:00:01.000 --> 00:00:03.500|สวัสดีครับ
00:00:04.000 --> 00:00:06.000|Hello world
```

### TXT แบบ plain text

```text
สวัสดีครับ
นี่คือบรรทัดที่สอง
Hello world
```

ใน UI เลือกได้ว่าให้กระจายเวลาตามความยาววิดีโอ หรือใช้ duration ต่อบรรทัด เช่น 3 วินาทีต่อบรรทัด

### CSV

ต้องมี header `start,end,text`

```csv
start,end,text
00:00:01.000,00:00:03.000,Hello world
00:00:04.000,00:00:06.000,สวัสดีครับ
```

ถ้าข้อความมี comma ให้ครอบด้วยเครื่องหมาย quote:

```csv
start,end,text
00:00:01.000,00:00:03.000,"Hello, world"
```

### JSON

```json
[
  {"start": "00:00:01.000", "end": "00:00:03.000", "text": "Hello"},
  {"start": "00:00:04.000", "end": "00:00:06.000", "text": "World"}
]
```

## การจัดตำแหน่งอัตโนมัติ

แอปคำนวณ layout จาก resolution จริงของวิดีโอ:

- Landscape: ใช้ subtitle ล่างกลางและ safe margin ประมาณ 7% ของความสูง
- Portrait: ใช้ subtitle ล่างกลาง แต่ยกขึ้นมากกว่า landscape ประมาณ 10% ของความสูง
- Square/อื่นๆ: ใช้ safe margin กลางๆ ประมาณ 8%
- ถ้า `Bottom margin` เป็น `0` จะใช้ค่า auto
- ถ้าตั้ง `Text position` เป็น `Custom` จะใช้ตำแหน่ง X/Y เป็นเปอร์เซ็นต์ของเฟรม
- ข้อความจะถูก wrap จากความกว้างวิดีโอจริง, font size และ `Max width`
- ภาษาไทยใช้ PyThaiNLP ช่วยตัดคำก่อน wrap เพื่อเลี่ยงการตัดกลางคำ
- มีตัวซ่อม token ภาษาไทยเพื่อกันเคสแยกคำผิด เช่น `ร` + `ะหว่าง`
- ถ้ายาวเกินจำนวน `Max lines` โปรแกรมจะตัดท้ายด้วย `...` เพื่อไม่ให้ตกขอบ
- ถ้าใช้ `Auto Arrange Text` โปรแกรมจะพยายามแตกข้อความยาวเป็นหลาย subtitle แทนการตัดท้าย เพื่อให้ดูเป็นธรรมชาติกว่า
- ค่า default ของ `Max lines` คือ 2 บรรทัด

## แก้ subtitle ก่อน export

หลัง parse subtitle แล้วสามารถแก้ในตารางได้โดยตรง และ preview ด้านขวาจะอัปเดตจากข้อมูลล่าสุด:

- double click ที่ `Start` หรือ `End` เพื่อเปลี่ยนเวลา
- double click ที่ `Text` เพื่อแก้คำพูด
- ใช้ช่อง `Selected subtitle text / line breaks` เพื่อแก้ข้อความหลายบรรทัด กด Enter เพื่อบังคับขึ้นบรรทัด
- กด `Apply Edits` เพื่อยืนยันค่าจากตาราง
- กด `Apply Text` เพื่อส่งข้อความจากช่อง multi-line editor เข้าแถวที่เลือก
- กด `Add Subtitle` เพื่อเพิ่ม subtitle แถวใหม่
- เลือกแถวแล้วกด `Delete Selected` เพื่อลบ
- เลือกแถวแล้วกด `Preview Selected` เพื่อ seek วิดีโอไปยังจุดเริ่มของ subtitle นั้น
- กด `Play` เพื่อดู subtitle วิ่งตาม timeline จริงก่อน export
- กด `Full Preview` เพื่อดู preview เต็มจอ

ปุ่ม `Auto Timing Cleanup` จะช่วยตัด subtitle ที่ค้างนานเกินไปหลังเสียงพูดหยุด โดยใช้:

- ช่วงเงียบจากเสียงวิดีโอผ่าน FFmpeg `silencedetect`
- ความยาวข้อความและจำนวนบรรทัดหลัง wrap
- เวลาเริ่มของ subtitle ถัดไป เพื่อไม่ให้ subtitle ชนกัน
- ค่า `Hold after speech`, `Min`, และ `Max` ในหน้าโปรแกรม

ปุ่ม `Auto Arrange Text` จะช่วย:

- ตัดคำภาษาไทย/อังกฤษก่อนจัดบรรทัด
- จำกัดจำนวนบรรทัดตามค่า `Max lines`
- แตก subtitle ยาวเป็นหลาย cue และกระจายเวลาในช่วง cue เดิม
- ลด `Max width` ถ้ากว้างเกิน safe area
- ลด stroke ที่หนาเกินไปจนกินตัวอักษร
- เปิด stroke อัตโนมัติถ้าไม่มี stroke/background/shadow เลย เพื่อให้อ่านง่ายขึ้น

สำหรับ style ที่เปิด background เช่น TikTok และ Documentary โปรแกรมจะใช้ background box เดียวครอบหลายบรรทัด ไม่วาดกล่องซ้อนกันทีละบรรทัด

## Preset Style

มี preset เริ่มต้น:

- Clean
- YouTube
- TikTok
- Documentary

ปุ่ม `Auto Size` จะคำนวณ font size และ bottom margin จากขนาดวิดีโอจริง

## Export

แอปใช้ FFmpeg command ภายในประมาณนี้:

```text
ffmpeg -i input.mp4 -vf ass=subtitle.ass -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -c:a aac -b:a 192k output.mp4
```

ไฟล์ output จะเป็น hard subtitle คือข้อความถูกฝังลงในภาพวิดีโอแล้ว

## Export Subtitle แยก

กด `Export Edited Subtitle` เพื่อบันทึก subtitle ที่แก้ในตารางแล้ว:

- `.srt` และ `.vtt` เหมาะสำหรับอัปโหลดลง YouTube, TikTok, Facebook หรือแพลตฟอร์มอื่น แต่จะไม่เก็บ style เช่น font, stroke, background
- `.ass` เก็บ style และ layout ใกล้กับ preview/export video มากที่สุด เหมาะสำหรับใช้กับ FFmpeg หรือ player ที่รองรับ ASS
- `.json`, `.csv`, `.txt` เหมาะสำหรับนำไปแก้ต่อหรือใช้กับ workflow อื่น

ก่อน export subtitle โปรแกรมจะ sync ค่าล่าสุดจากตารางเสมอ ทั้งคำพูด เวลาเริ่ม เวลาออก และ line break ที่แก้ไว้

## ข้อจำกัดที่ควรรู้

- Background box ใช้ ASS `BorderStyle=3` ซึ่งอาจแสดง padding/outline ต่างกันเล็กน้อยตาม FFmpeg/libass
- Shadow blur ใช้ ASS override tag `\blur` เป็นวิธีที่เรียบง่ายและใช้งานจริงได้
- Word wrapping ภาษาไทยใช้การตัดตามจำนวนตัวอักษรโดยประมาณ ยังไม่ใช่ NLP segmentation เต็มรูปแบบ
- ถ้า font ที่เลือกไม่มี glyph ภาษาไทย FFmpeg/libass อาจ fallback แตกต่างจาก preview ใน GUI

## แนวทางต่อยอด

- เพิ่ม karaoke effect ด้วย ASS override tag เช่น `\k`
- เพิ่ม soft subtitle mode ด้วย `-c:s mov_text`
- เพิ่ม template/preset เป็นไฟล์ JSON ภายนอก
- เพิ่ม line breaking ภาษาไทยด้วย library segmentation
- เพิ่ม preview video จริงด้วย Qt Multimedia
