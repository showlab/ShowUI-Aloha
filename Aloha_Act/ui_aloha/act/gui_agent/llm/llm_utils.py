import os
import re
import base64


def is_image_path(text):
    # Checking if the input text ends with typical image file extensions
    image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif")
    if text.endswith(image_extensions):
        return True
    else:
        return False

def encode_image(image_path):
    """Encode image file to base64."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def is_url_or_filepath(input_string):
    # Check if input_string is a URL
    url_pattern = re.compile(
        r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
    )
    if url_pattern.match(input_string):
        return "URL"

    # Check if input_string is a file path
    file_path = os.path.abspath(input_string)
    if os.path.exists(file_path):
        return "File path"

    return "Invalid"

def extract_data(input_string, data_type):
    # Regular expression to extract content starting from '```python'
    # until the end if there are no closing backticks
    pattern = f"```{data_type}" + r"(.*?)(```|$)"
    # Extract content
    # re.DOTALL allows '.' to match newlines as well
    matches = re.findall(pattern, input_string, re.DOTALL)
    # Return the first match if exists, trimming whitespace and ignoring potential closing backticks
    return matches[0][0].strip() if matches else input_string


def gbk_encode_decode(text):
    # Encode the text to GBK, ignoring characters that can't be encoded
    # Then decode it back to a string
    cleaned_text = text.encode('gbk', 'ignore').decode('gbk')
    return cleaned_text

# Compile a regex pattern to match any Chinese character in the range \u4e00-\u9fff.
def decode_chn(s):
    # If the string contains a literal "\u", decode it.
    if '\\u' in s:
        return s.encode('utf-8').decode('unicode-escape')
    return s


def remove_emojis_and_noise(text):
    # Encode the text to GBK, ignoring characters that can't be encoded
    # Then decode it back to a string
    cleaned_text = text.encode('gbk', 'ignore').decode('gbk')
    return cleaned_text