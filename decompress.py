from __future__ import annotations
from typing import Dict, Optional, Tuple
import heapq
import sys
import json
import collections

class Node:
    def __init__(self, left=None, right=None, word=None, freq=0) -> None:
        self.left: Optional[Node] = left
        self.right: Optional[Node] = right
        self.word: Optional[str] = word
        self.freq: int = freq
        pass

    def isLeaf(self) -> bool:
        return self.left is None and self.right is None

    def __lt__(self, other: Node) -> bool:
        return self.freq < other.freq


class HuffmanCompression:    
    @staticmethod
    def decompress_content(root: Node, compressed_binary_string: str) -> str:
        decompressed_content = ""
        curr_node = root
        for char in compressed_binary_string:
            if curr_node and char == "0":
                curr_node = curr_node.left
            elif curr_node and char == "1":
                curr_node = curr_node.right
            if curr_node and curr_node.isLeaf() and curr_node.word:
                decompressed_content += curr_node.word
                curr_node = root
        return decompressed_content

    @staticmethod
    def worker_huffman_build_tree( freq_table: Dict[str, int]) -> Node:
        heap = []
        freq_table = collections.OrderedDict(sorted(freq_table.items()))
        for word, freq in freq_table.items():
            heap.append(Node(word=word, freq=freq))
        heapq.heapify(heap)
        # assumes there are at least 2 different symbols in the table
        while len(heap) != 1:
            node1: Node = heapq.heappop(heap)
            node2: Node = heapq.heappop(heap)
            freq_sum = node1.freq + node2.freq
            new_parent_node = Node(freq=freq_sum, left=node1, right=node2)
            heapq.heappush(heap, new_parent_node)
        return heap[0]
   
    @staticmethod
    def convert_bytearray_to_string(
         byte_array: bytearray, original_length: int
    ) -> str:
        binary_string = "".join(format(byte, "08b") for byte in byte_array)
        return binary_string[:original_length]

    @staticmethod
    def read_compressed_binary_file(
         path_input: str
    ) -> Tuple[str, Dict[str, int]]:
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


    @staticmethod
    def decompress_file(path_input: str, path_output: str):
        file_binary_string, frequency_table = HuffmanCompression.read_compressed_binary_file(
            path_input=path_input
        )
        root = HuffmanCompression.worker_huffman_build_tree(freq_table=frequency_table)
        decompressed_content = HuffmanCompression.decompress_content(
            compressed_binary_string=file_binary_string, root=root
        )
        with open(path_output, "w") as f:
            f.write(decompressed_content)
            
            
compressed_file_name = sys.argv[1]
decompressed_file_name = sys.argv[2]
HuffmanCompression.decompress_file(path_input=f"./{compressed_file_name}", path_output=f"./{decompressed_file_name}")

