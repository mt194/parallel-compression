from __future__ import annotations
from typing import Dict, Optional, List, Tuple
from kazoo.client import KazooClient
from kazoo.recipe.barrier import Barrier
import collections
import re
import heapq
import json
import logging
import os
import requests
import time

logging.basicConfig()
API_SERVICE_IP = "http://apiservice.compression-namespace.svc.cluster.local:8080"
# MINIKUBE_NODE_IP = "192.168.49.2"
# MINIKUBE_NODE_IP = get_service_cluster_ip(service_name="zk-cs", namespace="compression-namespace")
ZOOKEEPER_SERVICE_IP = "zk-cs.compression-namespace.svc.cluster.local"
NODE_PORT = "2181"
zk = KazooClient(hosts=f"{ZOOKEEPER_SERVICE_IP}:{NODE_PORT}", timeout=30)
print("Created kazoo client instance")
zk.start(timeout=30)
print("Connection to ZK initiated")


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
    def __init__(
        self,
        worker_number: int,
        number_of_workers: int,
        zk: KazooClient,
        zk_barrier: Barrier,
    ):
        self.worker_number = worker_number
        self.number_of_workers = number_of_workers
        self.zk = zk
        self.zk_barrier = zk_barrier

    @staticmethod
    def get_worker_sub_freq_table_node_path(worker_number: int) -> str:
        return f"/root/sub-freq-tables/worker-{worker_number}-sub-freq-table"

    def get_text_symbols(self, text: str) -> List[str]:
        list_text_tokens = re.split(r"(\s)", text)
        list_text_tokens = [x for x in list_text_tokens if x != ""]
        return list_text_tokens

    def divide_symbols_among_workers(self, list_symbols: List[str]):
        if len(list_symbols) < self.number_of_workers:
            print("ERROR: Cannot have more workers than symbols")
            raise Exception()
        num_of_symbols_to_count = len(list_symbols) // self.number_of_workers
        start_index = (self.worker_number - 1) * num_of_symbols_to_count
        end_index = self.worker_number * num_of_symbols_to_count
        list_symbols_worker = []
        if (
            self.number_of_workers == self.worker_number
        ):  # last worker takes the last chunk no matter how big, because the number of symbols may not be divisible by the number of workers
            list_symbols_worker = list_symbols[start_index:]
            print(
                f"Worker {self.worker_number} processing from {start_index} to the end. Total items: {len(list_symbols)}"
            )
        else:
            list_symbols_worker = list_symbols[start_index:end_index]
            print(
                f"Worker {self.worker_number} processing from {start_index} to {end_index} (exclusive) Total items: {len(list_symbols)}"
            )
        return list_symbols_worker

    def worker_huffman_count(self, text_symbols: List[str]) -> Dict[str, int]:
        # Count frequency of characters
        worker_freq_table = {}
        for symbol in text_symbols:
            if symbol in worker_freq_table:
                worker_freq_table[symbol] += 1
            else:
                worker_freq_table[symbol] = 1
        return worker_freq_table

    def worker_huffman_generate_coding_table(self, root: Node) -> Dict[str, str]:
        codingTable = {}
        self.worker_huffman_generate_coding_table_rec(
            root=root, binary_string="", coding_table=codingTable
        )
        return codingTable

    def worker_huffman_generate_coding_table_rec(
        self, root: Node, binary_string: str = "", coding_table: Dict[str, str] = {}
    ):
        # Build coding table
        if root.isLeaf() and root.word is not None:
            coding_table[root.word] = binary_string
        else:
            if root.left:
                self.worker_huffman_generate_coding_table_rec(
                    root=root.left,
                    binary_string=binary_string + "0",
                    coding_table=coding_table,
                )
            if root.right:
                self.worker_huffman_generate_coding_table_rec(
                    root=root.right,
                    binary_string=binary_string + "1",
                    coding_table=coding_table,
                )

    def compress_content(self, coding_table: Dict[str, str], text_symbols: str) -> str:
        compressed_text = ""
        for symbol in text_symbols:
            compressed_text += coding_table[symbol]
        return compressed_text

    def send_compressed_chunk_to_api_service(self, path_output: str):
        with open(path_output, "rb") as f:
            requests.post(
                url=f"{API_SERVICE_IP}/upload-encoded-chunk",
                files={"upload_file": f},
                data={
                    "worker_number": self.worker_number,
                    "number_of_workers": self.number_of_workers,
                },
            )

    def merge_subfrequency_tables(self, sub_freq_tables: List[Dict[str, int]]):
        freq_table_keys = set()
        for sub_freq_table in sub_freq_tables:
            freq_table_keys |= sub_freq_table.keys()
        merged_freq_table = {key: 0 for key in freq_table_keys}
        for key in freq_table_keys:
            for sub_freq_table in sub_freq_tables:
                merged_freq_table[key] += sub_freq_table.get(key, 0)
        return merged_freq_table

    def compress_and_upload_chunk(self, path_input: str, path_output: str):
        content = ""
        with open(path_input, "r") as f:
            content = f.read()

        # Compression
        list_symbols = self.get_text_symbols(text=content)
        list_symbols_curr_worker = self.divide_symbols_among_workers(
            list_symbols=list_symbols
        )
        sub_freq_table = self.worker_huffman_count(
            text_symbols=list_symbols_curr_worker
        )
        # Synchronize frequency tables
        self.zk.ensure_path(f"/root/sub-freq-tables/")
        self.zk.create(
            HuffmanCompression.get_worker_sub_freq_table_node_path(
                worker_number=self.worker_number
            ),
            json.dumps(sub_freq_table).encode("utf-8"),
        )
        if self.worker_number == 1:
            # Leader waits until all workers have counted frequencies to remove the barrier
            print("Leader: Waiting for frequency tables to remove barrier")
            while (
                len(self.zk.get_children("/root/sub-freq-tables"))
                < self.number_of_workers
            ):
                time.sleep(1)
            print("Leader: Removing Barrier")
            self.zk_barrier.remove()
        else:
            print("Secondary worker: Waiting for barrier to be removed")
            self.zk_barrier.wait()

        print(
            f"Found {len(self.zk.get_children('/root/sub-freq-tables'))} subfrequency tables in the sub-freq-tables directory"
        )
        print(f"Number of workers: {self.number_of_workers}")
        list_sub_freq_tables = [sub_freq_table]
        for worker_number in range(1, self.number_of_workers + 1):
            if worker_number != self.worker_number:
                worker_subfreq_table_node = (
                    HuffmanCompression.get_worker_sub_freq_table_node_path(
                        worker_number=worker_number
                    )
                )
                if not self.zk.exists(worker_subfreq_table_node):
                    print(f"ERROR {worker_subfreq_table_node} does not exist")
                    raise Exception()
                diff_worker_sub_freq_table_binary, stat = self.zk.get(
                    worker_subfreq_table_node
                )
                diff_worker_sub_freq_table = json.loads(
                    diff_worker_sub_freq_table_binary.decode("utf-8")
                )
                list_sub_freq_tables.append(diff_worker_sub_freq_table)
        merged_freq_table = self.merge_subfrequency_tables(
            sub_freq_tables=list_sub_freq_tables
        )
        print(f"Merged all {len(list_sub_freq_tables)} subfrequency tables.")
        root = self.worker_huffman_build_tree(freq_table=merged_freq_table)
        coding_table = self.worker_huffman_generate_coding_table(root=root)
        compressed_text_binary_string = self.compress_content(
            text_symbols=list_symbols_curr_worker, coding_table=coding_table
        )

        # Writing binary data to collecting service
        HuffmanCompression.write_compressed_data_to_file(
            path_output=path_output,
            binary_string=compressed_text_binary_string,
            freq_table=merged_freq_table,
        )
        self.send_compressed_chunk_to_api_service(path_output=path_output)

        # CHECK binary data hasn't changed when written/read
        # file_binary_string, frequency_table = read_compressed_binary_file(
        #     path_input=path_output
        # )
        # print(compressed_text_binary_string == file_binary_string)

        # CHECK compressed and decompressed data are the same
        # decompressed_content = decompress_content(
        #     compressed_binary_string=file_binary_string, root=root
        # )
        # print(decompressed_content == content)

    @staticmethod
    def worker_huffman_build_tree(freq_table: Dict[str, int]) -> Node:
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
    def decompress_file(path_input: str, path_output: str):
        file_binary_string, frequency_table = (
            HuffmanCompression.read_compressed_binary_file(path_input=path_input)
        )
        root = HuffmanCompression.worker_huffman_build_tree(freq_table=frequency_table)
        decompressed_content = HuffmanCompression.decompress_content(
            compressed_binary_string=file_binary_string, root=root
        )
        with open(path_output, "w") as f:
            f.write(decompressed_content)

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


# compress_file(
#     path_input="./odyssey.txt", path_output="./compressed-binary-words.bin"
# )
# decompress_file(
#     path_input="./compressed-binary-words.bin",
#     path_output="./decompressed-content.txt",
# )


number_of_workers = int(os.environ.get("WORKER_NUMBER", 1))
current_worker_number = None
worker_index_node = "/root/worker-index"
worder_index_lock = "/root/worker-index-lock"
zk_node_lock = zk.Lock(path=worder_index_lock)
zk_barrier = Barrier(client=zk, path="/root/sub-freq-tables-barrier")
print("Acquiring lock")
with zk_node_lock:
    print("Lock acquired")
    if zk.exists(worker_index_node):
        # Configuring worker index
        data, stat = zk.get(worker_index_node)
        listWorkers = json.loads(data.decode("utf-8"))
        if len(listWorkers) > number_of_workers:
            print(
                f"ERROR: Zookeeper workers: {listWorkers}, number_of_workers: {number_of_workers} "
            )
            raise Exception()
        current_worker_number = len(listWorkers) + 1
        print(
            f"I am worker {current_worker_number}, out of {number_of_workers} workers"
        )
        listWorkers.append(current_worker_number)
        zk.set(worker_index_node, json.dumps(listWorkers).encode("utf-8"))
    else:
        # Configure First worker index
        zk.ensure_path("/root")
        current_worker_number = 1
        print("I am worker 1, creating worker index node and barrier")
        zk.create(
            worker_index_node, json.dumps([current_worker_number]).encode("utf-8")
        )
        zk_barrier.create()
print("Lock released")
# Taking a chunk of the document according to worker index
huffmanCompression = HuffmanCompression(
    zk=zk,
    number_of_workers=int(number_of_workers),
    worker_number=current_worker_number,
    zk_barrier=zk_barrier,
)
huffmanCompression.compress_and_upload_chunk(
    path_input="./odyssey.txt",
    path_output="/tmp/output.bin",
)
