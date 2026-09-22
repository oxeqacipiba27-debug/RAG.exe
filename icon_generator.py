from PIL import Image, ImageDraw, ImageFont

def create_icon():
    # Create a dark background image
    img = Image.new('RGBA', (256, 256), color=(30, 30, 30, 255))
    d = ImageDraw.Draw(img)
    
    # Try to load Arial or fallback to default
    try:
        font = ImageFont.truetype("arialbd.ttf", 120)
    except:
        font = ImageFont.load_default()
        
    text = "RAG"
    # Get bounding box
    bbox = d.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    
    # Draw centered text
    d.text(((256-w)/2, (256-h)/2 - 20), text, fill=(100, 200, 255, 255), font=font)
    
    # Draw a little accent line
    d.rectangle([(50, 180), (206, 190)], fill=(0, 120, 255, 255))
    
    img.save("w:/schoolX/rag_icon.png")

if __name__ == "__main__":
    create_icon()
