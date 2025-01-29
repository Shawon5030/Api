import fitz
import os
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import requests
import logging
from rest_framework import serializers
from django.http import HttpResponse
import re

class PDFUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

logger = logging.getLogger(__name__)

def home(request):
    return HttpResponse("Welcome to the PDF Parsing API")

class PDFParsingAPIView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = PDFUploadSerializer(data=request.data)
        if serializer.is_valid():
            pdf_file = serializer.validated_data['file']
            extracted_text, image_urls = self.extract_text_and_images_from_pdf(pdf_file)
            json_data = self.convert_text_to_json_rowwise(extracted_text)

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
                    # Save image locally
                    image_path = os.path.join(settings.MEDIA_ROOT, f"extracted_image_{xref}.{image_ext}")
                    with open(image_path, 'wb') as image_file:
                        image_file.write(image_bytes)
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

    def convert_text_to_json_rowwise(self, text):
        """
        Converts extracted text into a structured row-wise JSON format.
        Each line will have 'ok' as the key and the line text as the value.
        """
        try:
            lines = text.splitlines()
            # structured_data should be unique and not contain duplicate keys
            structured_data = []
            seen_keys = set()
            short = ['Upozila', "Village/Road", "Home/Holding", "Union/Ward", "Post Office", "RMO"]
            skip_keys = [
                "Village/Road", "Blood Group","Union/Ward", "Home/Holding", "National ID", "Voter Area", "Pin", "Postal Code", "Voter No", "Name(Bangla)", "Post Office",
                "Name(English)", "Date of Birth", "Birth Place", "Father Name", "Mother Name", "Spouse Name",
                "Gender", "Marital", "Occupation", "Division", "District", "RMO", "Upozila"
            ]
            home = ["Home/Holding"]
            blood_groups = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
            

            def is_bengali(word):
                # Regular expression for Bengali characters
                bengali_pattern = re.compile(r'[\u0980-\u09FF]')
                # If the word contains Bengali characters, return True
                return bool(bengali_pattern.search(word))

            for i in range(len(lines) - 1):
                if lines[i] in ["Corporation", "Or", "Municipality", "No"] or lines[i + 1] == "Additional":
                    continue
                current_line = lines[i].strip()
                next_line = lines[i + 1].strip()

                if current_line in skip_keys and current_line not in seen_keys:
                    if current_line:
                        # Ensure current line is not empty
                        if current_line in short:
                            next_line1 = lines[i + 2].strip()
                            if is_bengali(next_line1):
                                if current_line in home:
                                    if is_bengali(lines[i + 2].strip()) and not is_bengali(lines[i + 3].strip()):
                                        structured_data.append({current_line: lines[i + 2].strip()})
                                    elif is_bengali(lines[i + 2].strip()) and is_bengali(lines[i + 3].strip()):
                                        structured_data.append({current_line: lines[i + 2].strip() + ' ' + lines[i + 3].strip()})
                                    elif not is_bengali(lines[i + 2].strip()):
                                        structured_data.append({current_line: 'NaN'})
                                else:
                                    structured_data.append({current_line: next_line + ' ' + next_line1})
                                seen_keys.add(current_line)
                                continue
                            

                        if current_line == "Home/Holding" and "No" in next_line:
                            next_line = next_line.replace("No", "NAN").strip()
                        if current_line ==  "Blood Group" and next_line not in blood_groups:
                            next_line = next_line.replace(next_line, "NAN").strip()                           
                            
                        structured_data.append({current_line: next_line})  # Pair current line with the next line
                        seen_keys.add(current_line)

            logger.debug(f"Structured row-wise data: {structured_data}")
            return structured_data 
        except Exception as e:
            # showing errors
            logger.error(f"Error converting text to JSON: {e}")
            return []

# Ensure the response is encoded in UTF-8
def json_response(data, status=status.HTTP_200_OK):
    return Response(data, status=status, content_type='application/json; charset=utf-8')

