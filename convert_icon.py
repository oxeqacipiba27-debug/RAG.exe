from PIL import Image

def convert_to_ico():
    img = Image.open("w:/schoolX/rag_icon.png")
    img.save("w:/schoolX/rag_icon.ico", format="ICO", sizes=[(256, 256)])

if __name__ == "__main__":
    convert_to_ico()
