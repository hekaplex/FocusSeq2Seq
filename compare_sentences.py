import difflib
import os
import textwrap
from difflib import SequenceMatcher
import jellyfish
from strsimpy.longest_common_subsequence import LongestCommonSubsequence
from strsimpy.ngram import NGram

file = "input_output_examples.txt"

all_text = []
with open(file) as f:
    new_block = ""
    for line in f.readlines():
        if line.startswith("==="):
            all_text.append(new_block)
            new_block = ""
            continue
        new_block = new_block + line


if len(new_block):
    all_text.append(new_block)

twogram = NGram(2)
for e in all_text:
    if not len(e): continue
    tokens = e.split("Predicted summary:")
    summary = tokens[1].strip()
    input = tokens[0].strip().split("Input:")[1].strip()


    print("I: ",input)
    print("O: ",summary)
    print(twogram.distance(input,summary))
    print(twogram.distance(summary, input))
    print(twogram.distance("ana are mere si pere si portocale", "ana are ananas si masina si pere si portocale"))
    exit(0)

