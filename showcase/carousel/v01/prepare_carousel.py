"""Build review artwork from frozen project assets. Does not run or modify the game."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
import hashlib
import json
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCES = HERE / 'source-copies'
PREVIEWS = HERE / 'direction-previews'
for folder in (SOURCES, PREVIEWS, HERE / 'crops'):
    folder.mkdir(exist_ok=True)

paths = [
    'src/iron_and_snow/assets/winterfell_battlefield_panorama.png',
    'src/iron_and_snow/assets/winterfell_battlefield.png',
    'src/iron_and_snow/assets/jon_snow.png',
    'src/iron_and_snow/assets/ramsay_bolton.png',
    'src/iron_and_snow/assets/sprites/jon_snow_sheet.png',
    'src/iron_and_snow/assets/sprites/sansa_archer_sheet.png',
    'src/iron_and_snow/assets/sprites/tormund_giantsbane_sheet.png',
    'src/iron_and_snow/assets/sprites/wun_wun_sheet.png',
    'save/showcase-check/council.png',
    'save/showcase-check/council-recorded-live-reply.png',
    'save/showcase-check/conversation.png',
    'save/showcase-check/battle.png',
    'save/showcase-check/live-conversation-report.json',
    'save/showcase-check/live-codex-report.json',
    'save/showcase-check/performance.json',
    'src/iron_and_snow/check_showcase.py',
    'README.md', 'TICKETS.md',
]
manifest = []
for source in paths:
    target = SOURCES / source
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(ROOT / source, target)
    row = {'source': source, 'copy': str(target.relative_to(HERE)).replace('\\', '/'),
           'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    if target.suffix == '.png':
        with Image.open(target) as im:
            row['size'] = list(im.size)
    manifest.append(row)
(HERE / 'asset-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

BG = '#101b27'
INK = '#f1eee5'
GOLD = '#d6b56e'
MUTED = '#aebfcd'
PANEL = '#1b2a39'

def font(size, bold=False, serif=False):
    name = ('georgiab.ttf' if bold else 'georgia.ttf') if serif else ('segoeuib.ttf' if bold else 'segoeui.ttf')
    return ImageFont.truetype('C:/Windows/Fonts/' + name, size)

def write(im, xy, text, size=28, fill=INK, bold=False, serif=False, spacing=9):
    ImageDraw.Draw(im).multiline_text(xy, text, font=font(size, bold, serif), fill=fill, spacing=spacing)

def load(relative):
    return Image.open(SOURCES / relative).convert('RGBA')

def fit(im, source, box, cover=False, center=(.5,.5)):
    x,y,w,h = box
    source = source.copy()
    if cover:
        source = ImageOps.fit(source, (w,h), method=Image.Resampling.LANCZOS, centering=center)
    else:
        source.thumbnail((w,h), Image.Resampling.LANCZOS)
        x += (w-source.width)//2
        y += (h-source.height)//2
    im.paste(source,(x,y),source if source.mode == 'RGBA' else None)

def base(number, category):
    im=Image.new('RGB',(1080,1350),BG)
    write(im,(64,45),'IRON & SNOW',25,GOLD,True)
    write(im,(64,91),category,20,MUTED)
    write(im,(894,45),number,25,GOLD,True)
    ImageDraw.Draw(im).line((64,130,1016,130),fill='#425365',width=2)
    return im

def footer(im, line1, line2):
    ImageDraw.Draw(im).line((64,1200,1016,1200),fill='#425365',width=2)
    write(im,(64,1220),line1,22,MUTED)
    write(im,(64,1257),line2,22,MUTED)

art = 'src/iron_and_snow/assets/'
capture = 'save/showcase-check/'

im=base('01 / 07','DIRECTION DRAFT  /  GENERATED GAME ART')
write(im,(64,165),'A battlefield\nI can talk to.',76,INK,True,True,8)
write(im,(68,365),'Building a personal AI game experiment in Pygame.',29,MUTED)
fit(im,load(art+'winterfell_battlefield_panorama.png'),(0,445,1080,705),True,(.53,.5))
jon=load(art+'jon_snow.png')
fit(im,jon,(38,605,444,548))
ImageDraw.Draw(im).rectangle((538,963,1036,1119),fill=BG)
write(im,(564,986),'IRON & SNOW',37,INK,True,True)
write(im,(564,1043),"The Bastard’s Winter",27,GOLD)
footer(im,'Generated environment + character artwork.', 'Personal Game of Thrones fan-game / AI prototype.')
im.save(PREVIEWS/'01-artwork-cover.png')

im=base('02 / 07','DIRECTION DRAFT  /  COUNCIL PLAN')
write(im,(64,166),'Before the battle,\nask for a plan.',66,INK,True,True)
fit(im,load(capture+'council-recorded-live-reply.png'),(64,360,952,606))
write(im,(64,991),'CLOSE-UP  /  THE PROPOSED ASSIGNMENTS',22,GOLD,True)
crop=load(capture+'council-recorded-live-reply.png').crop((120,470,998,564))
crop.save(HERE/'crops/council-proposal.png')
fit(im,crop,(64,1039,952,104))
footer(im,'Current UI replaying a previously recorded real Codex reply.', 'Headless UI render; this frame does not show plan acceptance.')
im.save(PREVIEWS/'02-council-plan.png')

im=base('05 / 07','DIRECTION DRAFT  /  CONVERSATION CAMERA')
write(im,(64,166),'Even your enemy\ngets a turn.',66,INK,True,True)
shot=load(capture+'conversation.png')
fit(im,shot,(64,360,952,606))
d=ImageDraw.Draw(im)
scale=952/1100
def mark(rect, number):
    a,b,c,e=rect
    box=(int(64+a*scale),int(360+b*scale),int(64+c*scale),int(360+e*scale))
    d.rectangle(box,outline=GOLD,width=3)
    x,y=box[:2]
    d.rectangle((x,y-29,x+34,y),fill=GOLD)
    write(im,(x+5,y-28),str(number),20,BG,True)
mark((302,97,796,121),1)
mark((556,257,747,439),2)
write(im,(64,1002),'01  Combat pauses for the exchange.',30,INK,True)
write(im,(64,1060),'02  The camera focuses on the responding NPC.',30,INK,True)
footer(im,'Headless behavioral-check capture; staged test scene.', 'Shows pause + camera focus, not a live dialogue recording.')
im.save(PREVIEWS/'05-conversation-focus.png')

# A visual inventory, with source categories visible on every card.
cards=[
    (art+'winterfell_battlefield_panorama.png','01  PANORAMA / strongest cover','Generated environment art'),
    (art+'winterfell_battlefield.png','02  ORIGINAL BATTLEFIELD','Generated art / alternate cover'),
    (art+'jon_snow.png','03  JON / hero overlay','Generated character art'),
    (art+'sprites/sansa_archer_sheet.png','04  SANSA / sprite detail','Generated animation sheet'),
    (capture+'council-recorded-live-reply.png','05  COUNCIL / proposed plan','Real reply replayed in current UI'),
    (capture+'council.png','06  COUNCIL / overview','Headless UI render / no live reply'),
    (capture+'conversation.png','07  RAMSAY / camera focus','Behavioral-check capture / staged'),
    (capture+'battle.png','08  BATTLE / reserve only','Altered test state / replace for gameplay'),
]
board=Image.new('RGB',(1600,1570),BG)
write(board,(48,25),'IRON & SNOW  /  ASSET SHORTLIST',39,INK,True,True)
write(board,(48,84),'Review board v01  •  source categories preserved  •  8 November 2026',24,MUTED)
for idx,(p,title,kind) in enumerate(cards):
    x=48+(idx%2)*780; y=145+(idx//2)*350
    ImageDraw.Draw(board).rectangle((x,y,x+744,y+326),fill=PANEL)
    fit(board,load(p),(x+12,y+12,720,240))
    write(board,(x+16,y+260),title,24,INK,True)
    write(board,(x+16,y+294),kind,21,GOLD)
board.save(HERE/'asset-shortlist.png')

overview=Image.new('RGB',(1152,564),BG)
write(overview,(24,14),'VISUAL DIRECTION  /  THREE SAMPLE SLIDES',25,GOLD,True)
for idx,path in enumerate(sorted(PREVIEWS.glob('*.png'))):
    fit(overview,Image.open(path),(24+idx*376,64,352,440))
write(overview,(24,520),'Seven-slide story proposed; samples are for direction review.',21,MUTED)
overview.save(HERE/'direction-overview.png')
print('Built asset shortlist, three 1080 x 1350 direction previews, crop, and manifest.')
