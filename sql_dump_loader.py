import os

import pandas as pd





def is_recording_line(line):
    tokens = line.split("|")
    if len(tokens) > 4 and tokens[0].isdigit() and tokens[1].isdigit() and tokens[2].isdigit() and tokens[
        3].isdigit(): return True
    return False


def extract(text):
    tokens = text.split("|")
    return "|".join(tokens[4:])


def process(file):
    header_flag = True
    header = ""
    body_accumulator = []
    all_articles = []
    errors = 0
    total = 0
    original_version = []
    transcribed_versions = []
    with open(file) as f:
        article = None
        for line in f.readlines():
            if header_flag:
                header = line.strip()
                header_flag = False
                continue

            if (is_recording_line(line)):
                if (len(body_accumulator)):
                    last_line = body_accumulator[-1]
                    body_accumulator = body_accumulator[:-1]  # remove the last line

                    all_tokens = last_line.split("|")
                    all_tokens = all_tokens[:-13]

                    body_accumulator.append("|".join(all_tokens))

                    body_accumulator = [p for p in body_accumulator if len(p.strip())]

                    article = " ".join(body_accumulator)
                    tokens = article.split("|")
                    if len(tokens) == 2:
                        base_version = tokens[0]
                        original_version.append(base_version)
                        transcribed_version = tokens[1]
                        transcribed_versions.append(transcribed_version)
                    else:
                        errors += 1
                        print("******* PROBLEMATIC:", article)
                    all_articles.append(article)
                    body_accumulator = []
                clean_text = extract(line)
                body_accumulator.append(clean_text)

                continue

            body_accumulator.append(line)

    if (len(body_accumulator)):
        last_line = body_accumulator[-1]
        body_accumulator = body_accumulator[:-1]  # remove the last line

        all_tokens = last_line.split("|")
        all_tokens = all_tokens[:-13]

        body_accumulator.append("|".join(all_tokens))

        body_accumulator = [p for p in body_accumulator if len(p.strip())]

        article = " ".join(body_accumulator)
        tokens = article.split("|")
        if len(tokens) == 2:
            base_version = tokens[0]
            original_version.append(base_version)
            transcribed_version = tokens[1]
            transcribed_versions.append(transcribed_version)
        else:
            errors += 1
            print("******* PROBLEMATIC:", article)
        all_articles.append(article)
        body_accumulator = []

    full_list_step1 = list(zip(original_version, transcribed_versions))
    entries_containing_speaker = 0

    original_noise_removed = []
    for index, entry in enumerate(full_list_step1):
        original, transcribed = entry
        print(index, transcribed)
        print(index, original)
        if "Speaker" in original:
            entries_containing_speaker += 1

            reconstructed_article = ""
            all_lines = []
            for line in original.split("\n"):
                if line.strip().startswith("Speaker "):
                    tokens = ' '.join(line.split()).split(" ")
                    reconstructed_line = " ".join(tokens[3:])
                    all_lines.append(reconstructed_line)
            original_noise_removed.append("\n".join(all_lines))
        else:
            original_noise_removed.append(original)

    #print(entries_containing_speaker)

    full_list_step1 = list(zip(original_noise_removed, transcribed_versions))
    entries_containing_speaker = 0

    df = pd.DataFrame(data=full_list_step1, columns=["original", "transcribed"])
    #df.to_hdf("01_generated_df.hdf5", key="df")


    original_noise_removed = []
    #for index, entry in enumerate(full_list_step1):
    #    original, transcribed = entry
    #    print(index, original)
    #    print(index, transcribed)

    return df


