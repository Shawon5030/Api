import fitz
import os
import cv2
import numpy as np
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import PDFUploadSerializer
import requests
import logging

logger = logging.getLogger(__name__)

class PDFParsingAPIView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = PDFUploadSerializer(data=request.data)
        if serializer.is_valid():
            pdf_file = serializer.validated_data['file']
            extracted_text, image_urls = self.extract_text_and_images_from_pdf(pdf_file)
            json_data = self.convert_text_to_json(extracted_text)

            return Response({"status": "success", "data": json_data, "images": image_urls}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def extract_text_and_images_from_pdf(self, pdf_file):
        pdf_document = fitz.open(stream=pdf_file.read(), filetype="pdf")
        extracted_text = ""
        image_urls = []
        imgbb_api_key = '33a679634ee463155694608f400ad0b2'  # Replace with your ImgBB API key

        for page in pdf_document:
            extracted_text += page.get_text()
            image_list = page.get_images(full=True)
            logger.debug(f"Found {len(image_list)} images on page {page.number}")
            
            for img_index, img in enumerate(image_list):
                xref = img[0]
                base_image = pdf_document.extract_image(xref)
                
                if base_image is None:
                    logger.warning(f"No image data found for xref {xref}")
                    continue

                image_bytes = base_image.get("image", None)
                image_ext = base_image.get("ext", None)  # Get the image extension
                
                if not image_bytes or not image_ext:
                    logger.warning(f"Image data or extension missing for xref {xref}")
                    continue

                try:
                    # Open and ensure the image is rendered using OpenCV
                    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
                    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
                    
                    if image is None:
                        logger.warning(f"Failed to decode image for xref {xref}")
                        continue
                    
                    # Save image locally
                    image_path = os.path.join(settings.MEDIA_ROOT, f"extracted_image_{xref}.{image_ext}")
                    cv2.imwrite(image_path, image)
                    logger.debug(f"Saved image to {image_path}")

                    # Upload image to ImgBB
                    with open(image_path, 'rb') as image_file:
                        response = requests.post(
                            f'https://api.imgbb.com/1/upload?key={imgbb_api_key}',
                            files={'image': image_file}
                        )
                        if response.status_code == 200:
                            image_url = response.json().get('data', {}).get('url', None)
                            if image_url:
                                image_urls.append(image_url)
                                logger.debug(f"Uploaded image to ImgBB: {image_url}")
                        else:
                            logger.error(f"Failed to upload image: {response.status_code} - {response.text}")
                except Exception as e:
                    logger.error(f"Error processing image with xref {xref}: {e}")

                # Clean up temporary file
                if os.path.exists(image_path):
                    os.remove(image_path)
                    logger.debug(f"Removed temporary file: {image_path}")

        pdf_document.close()
        return extracted_text, image_urls

    def convert_text_to_json(self, text):
        lines = text.splitlines()
        import json

        main_data = {}
        for i, value in enumerate(lines):
            if value in ["National ID", "Pin", "Voter No", "Name(Bangla)", "Home/Holding", "Name(English)", "Date of Birth", "Birth Place", "Father Name", "Mother Name", "Blood Group"]:
                if i + 1 < len(lines):  # Ensure the next line exists
                    main_data[value] = lines[i + 1]

        json_result = {}
        last_key = None
        for line in lines:
            if ':' in line:  # Key-value pair
                key, value = map(str.strip, line.split(':', 1))
                json_result[key] = value if value else "N/A"  # Assign "N/A" for missing values
                last_key = key
            elif line.strip():  # Non-empty lines without a colon
                if last_key and json_result[last_key] == "N/A":
                    json_result[last_key] = line.strip()  # Assign the line as the value for the last key
                else:
                    json_result[line.strip()] = "N/A"  # Assign "N/A" for lines without a colon

        return json_result, main_data


