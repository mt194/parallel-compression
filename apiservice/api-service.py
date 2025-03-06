from flask import Flask, request, Response
from typing import Tuple, Dict
import os
import json

app = Flask(__name__)
COMPRESSED_FILE_PATH = "/tmp/compressed_file.bin"
WORKER_FILES_DIR = "/tmp/worker-files"


class HuffmanCompression:
    @staticmethod
    def convert_string_to_bytearray(binary_string: str) -> bytearray:
        if len(binary_string) % 8 != 0:
            padding_length = 8 - (len(binary_string) % 8)
            binary_string += "0" * padding_length

        byte_array = bytearray()
        number_of_bits = 8
        for i in range(0, len(binary_string), number_of_bits):
            byte = binary_string[i : i + number_of_bits]
            byte_array.append(int(byte, 2))
        return byte_array

    @staticmethod
    def convert_bytearray_to_string(byte_array: bytearray, original_length: int) -> str:
        binary_string = "".join(format(byte, "08b") for byte in byte_array)
        return binary_string[:original_length]

    @staticmethod
    def write_compressed_data_to_file(
        path_output: str, binary_string: str, freq_table: Dict[str, int]
    ):
        binary_string_length = len(binary_string)
        freq_table_bytes_array = bytearray(json.dumps(freq_table).encode("utf_8"))
        compressed_content_byte_array = HuffmanCompression.convert_string_to_bytearray(
            binary_string=binary_string
        )
        with open(path_output, "wb") as f:
            f.write(binary_string_length.to_bytes(length=4, byteorder="big"))
            f.write(len(freq_table_bytes_array).to_bytes(length=4, byteorder="big"))
            f.write(freq_table_bytes_array)
            f.write(compressed_content_byte_array)

    @staticmethod
    def read_compressed_binary_file(path_input: str) -> Tuple[str, Dict[str, int]]:
        compressed_file_bytes = None
        binary_text_length = None
        with open(path_input, "rb") as f:
            compressed_data_length_bytes = f.read(
                4
            )  # First 4 bytes of the file is the original length of the compressed data
            binary_text_length = int.from_bytes(
                compressed_data_length_bytes, byteorder="big"
            )
            frequency_table_length_bytes = f.read(
                4
            )  # Second 4 bytes of the file is the length of the frequency table
            frequency_table_length = int.from_bytes(
                frequency_table_length_bytes, byteorder="big"
            )
            frequency_table_bytes = f.read(frequency_table_length)
            frequency_table_string = frequency_table_bytes.decode("utf-8")
            frequency_table_dict = json.loads(frequency_table_string)
            compressed_file_bytes = f.read()
        compressed_file_byte_array = bytearray(compressed_file_bytes)

        file_binary_string = HuffmanCompression.convert_bytearray_to_string(
            byte_array=compressed_file_byte_array, original_length=binary_text_length
        )
        return file_binary_string, frequency_table_dict


def get_num_of_files_in_dir(dir: str):

    return len([os.path.join(dir, f) for f in os.listdir(dir)])


def get_files_in_dir(dir: str):
    return [os.path.join(dir, f) for f in os.listdir(dir)]


@app.get("/")
def fetch_compressed_file():
    with open(COMPRESSED_FILE_PATH, "rb") as f:
        binary_data = f.read()
    response = Response(binary_data, content_type="application/octet-stream")

    # Add headers to suggest a download to the client
    response.headers["Content-Disposition"] = "attachment; filename=compressed_file.bin"
    return response


@app.post("/upload-encoded-chunk")
def upload_encoded_chunk():
    # Receive and save chunk to file syste
    # Check if we have chunks from all workers, if not don't do anything
    # Combine the chunks into one compressed blob ready to serve via the other route
    received_file = request.files["upload_file"]
    worker_number = request.form["worker_number"]
    number_of_workers = int(request.form["number_of_workers"])
    if not os.path.exists(WORKER_FILES_DIR):
        os.makedirs(WORKER_FILES_DIR)
    with open(f"{WORKER_FILES_DIR}/received_file_{worker_number}.bin", "wb") as f:
        f.write(received_file.read())
    if number_of_workers == get_num_of_files_in_dir(WORKER_FILES_DIR):
        # All chunks exist, merge to generate the final compressed file
        encoded_chunk_paths = sorted(get_files_in_dir(dir=WORKER_FILES_DIR))
        combined_file_binary_string = ""
        frequency_table = {}
        for encoded_chunk_path in encoded_chunk_paths:
            file_binary_string, frequency_table_dict = (
                HuffmanCompression.read_compressed_binary_file(
                    path_input=encoded_chunk_path
                )
            )
            frequency_table = frequency_table_dict
            combined_file_binary_string += file_binary_string
        HuffmanCompression.write_compressed_data_to_file(
            path_output=COMPRESSED_FILE_PATH,
            binary_string=combined_file_binary_string,
            freq_table=frequency_table,
        )

    return Response("{'status':'ok'}", status=201, mimetype="application/json")
