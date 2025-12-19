from google.cloud import vision
import io
import docx

def extract_text_from_file(file_content: bytes, mime_type: str) -> str:
    """
    Extracts text from an image, PDF, or Word file.
    - Uses Google Cloud Vision API for images and PDFs.
    - Uses python-docx library for Word (.docx) files.
    """
    client = vision.ImageAnnotatorClient()

    # Define the advanced feature configuration to use the latest model for Vision API.
    features = [
        vision.Feature(
            type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION,
            model="builtin/latest"
        )
    ]

    if mime_type in ['image/jpeg', 'image/png']:
        image = vision.Image(content=file_content)
        request = vision.AnnotateImageRequest(image=image, features=features)
        response = client.annotate_image(request=request)
        if response.error.message:
            raise Exception(response.error.message)
        return response.full_text_annotation.text

    elif mime_type == 'application/pdf':
        input_config = vision.InputConfig(content=file_content, mime_type=mime_type)
        request = vision.AnnotateFileRequest(input_config=input_config, features=features)
        response = client.batch_annotate_files(requests=[request])

        full_text = []
        for file_response in response.responses:
            if file_response.error.message:
                raise Exception(file_response.error.message)
            # The 'responses' list contains a separate response for each page
            for page_response in file_response.responses:
                if page_response.full_text_annotation:
                    full_text.append(page_response.full_text_annotation.text)

        return "\n\n--- Page Break ---\n\n".join(full_text)

    elif mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
        try:
            # Use io.BytesIO to read the file content in memory
            document = docx.Document(io.BytesIO(file_content))
            # Extract text from all paragraphs and join them
            return "\n".join([para.text for para in document.paragraphs])
        except Exception as e:
            raise Exception(f"Error processing .docx file: {e}")

    else:
        return "Unsupported File Type"
