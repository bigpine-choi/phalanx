param(
    [Parameter(Mandatory=$true)][string]$Before,
    [Parameter(Mandatory=$true)][string]$After,
    [Parameter(Mandatory=$true)][string]$Output,
    [int]$Seconds = 8
)
$ErrorActionPreference = 'Stop'
# Converts actual Godot MJPEG recordings to a portable, seekable preview.
# Every third recorded frame is retained: 30 FPS sources -> 10 FPS preview.
# It scales/compresses frames for delivery; no pose generation or interpolation.
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;

public static class AvatarMovieFrames {
    public static string[] Read(string path, int seconds, bool detail) {
        var frames = new List<string>();
        int videoIndex = 0;
        using (var reader = new BinaryReader(File.OpenRead(path))) {
            Scan(reader, reader.BaseStream.Length, frames, seconds * 10, ref videoIndex, detail);
        }
        if (frames.Count == 0) throw new InvalidDataException("No MJPEG video chunks found.");
        return frames.ToArray();
    }
    private static void Scan(BinaryReader reader, long end, List<string> frames, int limit, ref int videoIndex, bool detail) {
        while (reader.BaseStream.Position + 8 <= end && frames.Count < limit) {
            string tag = Encoding.ASCII.GetString(reader.ReadBytes(4));
            uint length = reader.ReadUInt32();
            long dataStart = reader.BaseStream.Position;
            long next = dataStart + length + (length & 1);
            if (next > reader.BaseStream.Length) break;
            if (tag == "RIFF" || tag == "LIST") {
                reader.ReadBytes(4);
                Scan(reader, dataStart + length, frames, limit, ref videoIndex, detail);
            } else if (tag == "00dc" || tag == "00db") {
                if (videoIndex++ % 3 == 0) {
                    byte[] bytes = reader.ReadBytes((int)length);
                    using (var encoded = new MemoryStream(bytes))
                    using (var source = Image.FromStream(encoded))
                    using (var thumbnail = new Bitmap(detail ? 460 : 640, detail ? 480 : (int)Math.Round(source.Height * 640.0 / source.Width)))
                    using (var graphics = Graphics.FromImage(thumbnail))
                    using (var target = new MemoryStream()) {
                        graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
                        graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
                        if (detail) graphics.DrawImage(source, new Rectangle(0, 0, 460, 480), new Rectangle(500, 260, 460, 480), GraphicsUnit.Pixel);
                        else graphics.DrawImage(source, 0, 0, thumbnail.Width, thumbnail.Height);
                        var settings = new EncoderParameters(1);
                        settings.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, detail ? 88L : 77L);
                        ImageCodecInfo jpeg = null;
                        foreach (var codec in ImageCodecInfo.GetImageEncoders()) if (codec.MimeType == "image/jpeg") jpeg = codec;
                        thumbnail.Save(target, jpeg, settings);
                        settings.Dispose();
                        frames.Add(Convert.ToBase64String(target.ToArray()));
                    }
                }
            }
            reader.BaseStream.Position = next;
        }
    }
}
'@
$beforePath = (Resolve-Path -LiteralPath $Before).Path
$afterPath = (Resolve-Path -LiteralPath $After).Path
$beforeFrames = [AvatarMovieFrames]::Read($beforePath, $Seconds, $false)
$afterFrames = [AvatarMovieFrames]::Read($afterPath, $Seconds, $false)
$beforeDetail = [AvatarMovieFrames]::Read($beforePath, $Seconds, $true)
$afterDetail = [AvatarMovieFrames]::Read($afterPath, $Seconds, $true)
$data = @{ before = $beforeFrames; after = $afterFrames; beforeDetail = $beforeDetail; afterDetail = $afterDetail } | ConvertTo-Json -Depth 4 -Compress
$template = @'
<!doctype html><html lang="en"><meta charset="utf-8"><title>Phalanx commander: actual render comparison</title>
<style>body{margin:24px;background:#101712;color:#e7ddc5;font:16px system-ui}h1{font-size:24px}p{max-width:1000px;color:#beb9a8}main{display:flex;gap:16px;flex-wrap:wrap}figure{margin:0;flex:1;min-width:360px;max-width:720px}img{width:100%;display:block;border:1px solid #5c5742}figcaption{padding:8px 0}button,input{accent-color:#dab974}button{padding:8px 24px;background:#dbbd7c;color:#20251c;border:0;border-radius:4px}input{width:min(700px,65vw);vertical-align:middle;margin:20px}small{color:#bbb7a9}</style>
<h1>Courtyard → headquarters entrance</h1><p>Actual Godot render, replayed using the same synthetic route. This is not an operating-system input or human play recording. The original AVI runs at 30 FPS; this portable preview retains every third frame at 10 FPS. Whole frames are resized proportionally; the detail panels are fixed 460×480 native-resolution crops of the same recorded frames. JPEG compression only: no generated or interpolated poses.</p>
<main><figure><figcaption>Before — single painted pose</figcaption><img id="before"></figure><figure><figcaption>After — articulated commander</figcaption><img id="after"></figure></main>
<main style="margin-top:18px"><figure style="max-width:460px"><figcaption>Before — actual feet and body, fixed native crop</figcaption><img id="beforeDetail"></figure><figure style="max-width:460px"><figcaption>After — actual feet and body, fixed native crop</figcaption><img id="afterDetail"></figure></main>
<button id="toggle">Pause</button><input id="seek" type="range" min="0" step="1"><span id="time"></span><p><small>The replay includes a reset after the first entrance arrival. Compare travel and settlement during the shared first segment; differing locomotion speeds may reach the entrance at different timestamps.</small></p>
<script>const frames=__FRAMES__;let index=0,playing=true;const count=Math.min(frames.before.length,frames.after.length);const seek=document.querySelector('#seek');seek.max=count-1;function draw(){for(const id of ['before','after','beforeDetail','afterDetail'])document.querySelector('#'+id).src='data:image/jpeg;base64,'+frames[id][index];seek.value=index;document.querySelector('#time').textContent=(index/10).toFixed(1)+' s';}document.querySelector('#toggle').onclick=()=>{playing=!playing;document.querySelector('#toggle').textContent=playing?'Pause':'Play'};seek.oninput=()=>{index=Number(seek.value);draw()};setInterval(()=>{if(playing){index=(index+1)%count;draw()}},100);draw();</script></html>
'@
[IO.File]::WriteAllText([IO.Path]::GetFullPath($Output), $template.Replace('__FRAMES__', $data), [Text.UTF8Encoding]::new($false))
Get-Item -LiteralPath $Output | Select-Object FullName, Length
