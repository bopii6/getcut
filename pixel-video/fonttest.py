from PIL import Image, ImageDraw, ImageFont
f = r"E:\getcut\pixel-video\assets\zpix.ttf"
for size in (12, 24, 36):
    font = ImageFont.truetype(f, size)
    img = Image.new("RGB", (300, 60), (24, 20, 37))
    d = ImageDraw.Draw(img)
    d.text((6, 6), "为什么越糊越高级", font=font, fill=(240, 236, 224))
    img.resize((img.width*4, img.height*4), Image.NEAREST).save(rf"E:\getcut\pixel-video\assets\fonttest_{size}.png")
print("ok")
