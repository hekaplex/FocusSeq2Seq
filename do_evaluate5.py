"""FocusSeq2Seq
Copyright (c) 2019-present NAVER Corp.
MIT license
"""

import time
import multiprocessing

import numpy as np
import torch

from utils import bleu, rouge
from utils.tensor_utils import repeat
from utils.data_utils import split_sentences
import datetime

if torch.cuda.is_available():
    device = 'cuda'
else:
    device = 'cpu'

n_cpus = multiprocessing.cpu_count()


def evaluate5(loader, model, epoch, config, expected, test=False):
    now = datetime.datetime.now()

    f = open("evaluation_" + str(now.hour) + str(now.minute) + str(now.second) + ".txt", "w")
    start = time.time()
    print('Evaluation start!')
    model.eval()
    if config.task == 'QG':
        references = loader.dataset.df.target_WORD.tolist()

    elif config.task == 'SM':
        # references = loader.dataset.df.target_tagged.tolist()
        references = loader.dataset.df.target_multiref.tolist()
        # references = loader.dataset.df.target.tolist()
    hypotheses = [[] for _ in range(max(config.n_mixture, config.decode_k))]
    hyp_focus = [[] for _ in range(max(config.n_mixture, config.decode_k))]
    hyp_attention = [[] for _ in range(max(config.n_mixture, config.decode_k))]

    if config.n_mixture > 1:
        assert config.decode_k == 1
        use_multiple_hypotheses = True
        best_hypothesis = []
    elif config.decode_k > 1:
        assert config.n_mixture == 1
        use_multiple_hypotheses = True
        best_hypothesis = []
    else:
        use_multiple_hypotheses = False
        best_hypothesis = None

    word2id = model.word2id
    id2word = model.id2word

    # PAD_ID = word2id['<pad>']
    vocab_size = len(word2id)

    n_iter = len(loader)
    temp_time_start = time.time()

    all_sources = []
    with torch.no_grad():
        for batch_idx, batch in enumerate(loader):
            if config.task == 'QG':
                source_WORD_encoding, source_len, \
                target_WORD_encoding, target_len, \
                source_WORD, target_WORD, \
                answer_position_BIO_encoding, answer_WORD, \
                ner, ner_encoding, \
                pos, pos_encoding, \
                case, case_encoding, \
                focus_WORD, focus_mask, \
                focus_input, answer_WORD_encoding, \
                source_WORD_encoding_extended, oovs \
                    = [b.to(device) if isinstance(b, torch.Tensor) else b for b in batch]

            elif config.task == 'SM':
                source_WORD_encoding, source_len, \
                target_WORD_encoding, target_len, \
                source_WORD, target_WORD, \
                focus_WORD, focus_mask, \
                focus_input, \
                source_WORD_encoding_extended, oovs \
                    = [b.to(device) if isinstance(b, torch.Tensor) else b for b in batch]
                answer_position_BIO_encoding = answer_WORD = ner_encoding = pos_encoding = case_encoding = None
                answer_WORD_encoding = None

            B, L = source_WORD_encoding.size()

            for source_input_line in source_WORD:
                all_sources.append(" ".join(source_input_line))
            if False:
                print("INPUT: ")
                print(source_WORD_encoding, source_len, \
                      target_WORD_encoding, target_len, \
                      source_WORD, target_WORD, \
                      focus_WORD, focus_mask, \
                      focus_input, \
                      source_WORD_encoding_extended, oovs)

            if config.use_focus:
                if config.eval_focus_oracle:

                    generated_focus_mask = focus_mask
                    input_mask = focus_mask

                else:
                    # [B * n_mixture, L]
                    focus_p = model.selector(
                        source_WORD_encoding,
                        answer_position_BIO_encoding,
                        ner_encoding,
                        pos_encoding,
                        case_encoding,
                        # mixture_id=mixture_id,
                        # focus_input=focus_input,
                        train=False)

                    generated_focus_mask = (focus_p > config.threshold).long()

                    # Repeat for Focus Selector
                    if config.n_mixture > 1:
                        source_WORD_encoding = repeat(
                            source_WORD_encoding, config.n_mixture)
                        if config.feature_rich:
                            answer_position_BIO_encoding = repeat(
                                answer_position_BIO_encoding, config.n_mixture)
                            ner_encoding = repeat(ner_encoding, config.n_mixture)
                            pos_encoding = repeat(pos_encoding, config.n_mixture)
                            case_encoding = repeat(case_encoding, config.n_mixture)
                        if config.model == 'PG':
                            source_WORD_encoding_extended = repeat(
                                source_WORD_encoding_extended, config.n_mixture)
                            assert source_WORD_encoding.size(0) \
                                   == source_WORD_encoding_extended.size(0)

                    input_mask = generated_focus_mask

            else:
                input_mask = None
                generated_focus_mask = focus_mask

            # [B*n_mixturre, K, max_len]
            prediction, score = model.seq2seq(
                source_WORD_encoding,
                answer_WORD_encoding=answer_WORD_encoding,
                answer_position_BIO_encoding=answer_position_BIO_encoding,
                ner_encoding=ner_encoding,
                pos_encoding=pos_encoding,
                case_encoding=case_encoding,
                focus_mask=input_mask,
                target_WORD_encoding=None,
                source_WORD_encoding_extended=source_WORD_encoding_extended,
                train=False,
                decoding_type=config.decoding,
                beam_k=config.beam_k,
                max_dec_len=30 if config.task == 'QG' else 120 if config.task == 'SM' else exit(),
                temperature=config.temperature,
                diversity_lambda=config.diversity_lambda)

            prediction = prediction.view(B, config.n_mixture, config.beam_k, -1)
            prediction = prediction[:, :, 0:config.decode_k, :].tolist()

            if use_multiple_hypotheses:
                score = score.view(B, config.n_mixture, config.beam_k)
                score = score[:, :, :config.decode_k].view(B, -1)
                # [B]
                best_hyp_idx = score.argmax(dim=1).tolist()

            # Word IDs => Words
            for batch_j, (predicted_word_ids, source_words, target_words) \
                    in enumerate(zip(prediction, source_WORD, target_WORD)):
                if config.n_mixture > 1:
                    assert config.decode_k == 1
                    for n in range(config.n_mixture):
                        predicted_words = []
                        # [n_mixture, decode_k=1, dec_len]
                        for word_id in predicted_word_ids[n][0]:
                            # Generate
                            if word_id < vocab_size:
                                word = id2word[word_id]
                                # End of sequence
                                if word == '<eos>':
                                    break
                            # Copy
                            else:
                                pointer_idx = word_id - vocab_size
                                if config.model == 'NQG':
                                    word = source_words[pointer_idx]
                                elif config.model == 'PG':
                                    try:
                                        word = oovs[batch_j][pointer_idx]
                                    except IndexError:
                                        import ipdb
                                        ipdb.set_trace()
                            predicted_words.append(word)

                        hypotheses[n].append(predicted_words)

                        if use_multiple_hypotheses and best_hyp_idx[batch_j] == n:
                            best_hypothesis.append(predicted_words)

                elif config.n_mixture == 1:
                    for k in range(config.decode_k):
                        predicted_words = []
                        # [n_mixture=1, decode_k, dec_len]
                        for word_id in predicted_word_ids[0][k]:
                            # Generate
                            if word_id < vocab_size:
                                word = id2word[word_id]
                                # End of sequence
                                if word == '<eos>':
                                    break
                            # Copy
                            else:
                                pointer_idx = word_id - vocab_size
                                if config.model == 'NQG':
                                    word = source_words[pointer_idx]
                                elif config.model == 'PG':
                                    try:
                                        word = oovs[batch_j][pointer_idx]
                                    except IndexError:
                                        import ipdb
                                        ipdb.set_trace()
                            predicted_words.append(word)

                        hypotheses[k].append(predicted_words)

                        if use_multiple_hypotheses and best_hyp_idx[batch_j] == k:
                            best_hypothesis.append(predicted_words)

            # For visualization
            if config.use_focus:
                # [B * n_mixture, L] => [B, n_mixture, L]
                focus_p = focus_p.view(B, config.n_mixture, L)
                generated_focus_mask = generated_focus_mask.view(B, config.n_mixture, L)
                # target_L x [B * n_mixture, L]
                # => [B * n_mixture, L, target_L]
                # => [B, n_mixture, L, target_L]
                attention_list = torch.stack(model.seq2seq.decoder.attention_list, dim=2).view(
                    B, config.n_mixture, L, -1)

                # n_mixture * [B, L]
                for n, focus_n in enumerate(focus_p.split(1, dim=1)):
                    # [B, 1, L] => [B, L]
                    focus_n = focus_n.squeeze(1).tolist()
                    # B x [L]
                    for f_n in focus_n:
                        hyp_focus[n].append(f_n)  # [L]

                # n_mixture * [B, L, target_L]
                for n, attention in enumerate(attention_list.split(1, dim=1)):
                    # [B, 1, L, target_L] => [B, L, target_L]
                    attention = attention.squeeze(1).tolist()
                    # B x [L, target_L]
                    for at in attention:
                        hyp_attention[n].append(np.array(at))  # [L, target_L]

            if (not test) and batch_idx == 0:
                # if batch_idx > 260:
                n_samples_to_print = min(10, len(source_WORD))
                for i in range(n_samples_to_print):
                    s = source_WORD[i]  # [L]
                    g_m = generated_focus_mask[i].tolist()  # [n_mixture, L]

                    f_p = focus_p[i].tolist()  # [n_mixture, L]

                    print(f'[{i}]')

                    print(f"Source Sequence: {' '.join(source_WORD[i])}")
                    if config.task == 'QG':
                        print(f"Answer: {' '.join(answer_WORD[i])}")
                    if config.use_focus:
                        print(f"Oracle Focus: {' '.join(focus_WORD[i])}")
                    if config.task == 'QG':
                        print(f"Target Question: {' '.join(target_WORD[i])}")
                    elif config.task == 'SM':
                        print(f"Target Summary: {' '.join(target_WORD[i])}")
                    if config.n_mixture > 1:
                        for n in range(config.n_mixture):
                            if config.use_focus:
                                print(f'(focus {n})')

                                print(
                                    f"Focus Prob: {' '.join([f'({w}/{p:.2f})' for (w, p) in zip(s, f_p[n])])}")
                                print(
                                    f"Generated Focus: {' '.join([w for w, m in zip(s, g_m[n]) if m == 1])}")
                            if config.task == 'QG':
                                print(
                                    f"Generated Question: {' '.join(hypotheses[n][B * batch_idx + i])}\n")
                            elif config.task == 'SM':
                                print(
                                    f"Generated Summary: {' '.join(hypotheses[n][B * batch_idx + i])}\n")
                    else:
                        for k in range(config.decode_k):
                            if config.use_focus:
                                print(f'(focus {k})')

                                print(
                                    f"Focus Prob: {' '.join([f'({w}/{p:.2f})' for (w, p) in zip(s, f_p[k])])}")
                                print(
                                    f"Generated Focus: {' '.join([w for w, m in zip(s, g_m[k]) if m == 1])}")
                            if config.task == 'QG':
                                print(
                                    f"Generated Question: {' '.join(hypotheses[k][B * batch_idx + i])}\n")
                            elif config.task == 'SM':
                                print(
                                    f"Generated Summary: {' '.join(hypotheses[k][B * batch_idx + i])}\n")

            if batch_idx % 100 == 0 or (batch_idx + 1) == n_iter:
                log_str = f'Evaluation | Epoch [{epoch}/{config.epochs}]'
                log_str += f' | Iteration [{batch_idx}/{n_iter}]'
                time_taken = time.time() - temp_time_start
                log_str += f' | Time taken: : {time_taken:.2f}'
                print(log_str)
                temp_time_start = time.time()

    time_taken = time.time() - start
    print(f"Generation Done! It took {time_taken:.2f}s")

    if test:
        print('Test Set Evaluation Result')

    score_calc_start = time.time()

    input_cnt = 0
    if not config.eval_focus_oracle and use_multiple_hypotheses:
        if config.task == 'SM':
            flat_hypothesis = best_hypothesis

            # summaries = [split_sentences(remove_tags(words))
            #              for words in flat_hypothesis]
            summaries = [split_sentences(words)
                         for words in flat_hypothesis]
            # references = [split_tagged_sentences(ref) for ref in references]

            # summaries = [[" ".join(words)]
            #              for words in flat_hypothesis]
            # references = [[ref] for ref in references]

            hypotheses_ = [[split_sentences(words) for words in hypothesis]
                           for hypothesis in hypotheses]

            nested_hypothesis_list = hypotheses[0]

            gt_summary = []
            predicted_hypo = []
            for nested_summary in summaries:
                gt_summary.append(nested_summary[0])

            for nested_pred in nested_hypothesis_list:
                predicted_text = " ".join(nested_pred)
                predicted_hypo.append(predicted_text)

            for xi in range(0, len(predicted_hypo)):
                print("=================================")
                print("Input:")
                print(all_sources[input_cnt])
                print("\n")
                f.write("Input:\n")
                f.write(all_sources[input_cnt] + "\n")
                f.write("\n\n")

                print("Expected:")
                print(expected[input_cnt])
                print("\n")

                f.write("Expected:\n")
                f.write(expected[input_cnt] + "\n")
                f.write("\n\n")

                input_cnt += 1
                # print("Target summary: ")
                # print(gt_summary[xi])
                # print("\n")

                print("Predicted summary: ")
                print(predicted_hypo[xi])
                clean_prediction = clean_predicted_hypo(predicted_hypo[xi])
                print("\n")

                f.write("Predicted summary:\n")
                f.write(predicted_hypo[xi] + "\n")
                f.write("\n\n")

                f.write("Cleaned Predicted summary:\n")
                f.write(clean_prediction + "\n")
                f.write("\n\n")

            # references = [split_tagged_sentences(ref) for ref in references]
            # hypotheses_ = [[[" ".join(words)] for words in hypothesis]
            #                for hypothesis in hypotheses]
            # references = [[ref] for ref in references]

    # return metric_result, hypotheses, best_hypothesis, hyp_focus, hyp_attention


from collections import Counter


def clean_predicted_hypo(unclean_hypo):
    sentences = unclean_hypo.split(".")
    last_sentence = sentences[-1]
    last_sentence_nr_of_words = len(last_sentence.split(" "))
    # check for the number of words
    if last_sentence_nr_of_words <= 3:
        full_text = ".".join(sentences[:-1]) + "."
        return full_text

    # check for stupid repetitions in the last sentence
    lower_tokens = [token.lower().strip() for token in last_sentence.strip().split(" ")]
    counts = Counter(lower_tokens)
    for key, count in counts.items():
        if count >= 5:
            full_text = ".".join(sentences[:-1]) + "."
            return full_text

    return unclean_hypo


def split_in_2(batch_of_text):
    all_text = []
    for entry in batch_of_text:
        entry = entry.replace("\n", " ")
        entry = entry.strip()
        tokens = entry.split(".")
        nr_of_sentences = len(entry.split("."))
        part1 = tokens[0:int(nr_of_sentences / 2)]
        part2 = tokens[int(nr_of_sentences / 2):]
        part1_text = ".".join(part1).strip() + "."
        part2_text = ".".join(part2).strip() + "."
        all_text.append(part1_text)
        all_text.append(part2_text)
    return all_text


"""
        part1 = tokens[0:int(nr_of_sentences / 3)]
        part2 = tokens[int(nr_of_sentences / 3):int(nr_of_sentences * 2 / 3)]
        part3 = tokens[int(nr_of_sentences * 2 / 3):]
        part1_text = ".".join(part1).strip() + "."
        part2_text = ".".join(part2).strip() + "."
        part3_text = ".".join(part3).strip() + "."
        all_text.append(part1_text)
        all_text.append(part2_text)
        all_text.append(part3_text)
"""


def return_original_real_input(file):
    import sql_dump_loader
    df = sql_dump_loader.process(file)
    return df


def prepare_real_life_evaluation():
    expected = None
    import oral_history_data_loader
    import pickle
    import os
    current_dir = Path(__file__).resolve().parent

    data_dir = current_dir.joinpath('oh/')
    out_dir = current_dir.joinpath('oh_out/')
    if not os.path.exists(out_dir):
        out_dir.mkdir()

    word2id, id2word = oral_history_data_loader.vocab_read(data_dir.joinpath('vocab'))

    real_dir = current_dir.joinpath('real/')
    batch_of_text = []

    full_path = os.path.join(real_dir, "original_real_input.txt")
    origina_df = return_original_real_input(full_path)
    all_articles = list(origina_df.original.values)

    expected = list(origina_df.transcribed.values)

    batch_of_text = [str(p).replace("\n", " ").strip() for p in all_articles]

    batch_of_expected = [str(p).replace("\n", " ").strip() for p in expected]
    #    with open(os.path.join(real_dir, "original_real_input.txt")) as f:
    #        batch = ""
    #        for line in f.readlines():
    #            if line.startswith("====="):
    #                batch_of_text.append(batch.strip().replace("\n", " "))
    #                batch = ""
    #            else:
    #                batch = batch + line

    #    if len(batch):
    #        batch_of_text.append(batch.strip().replace("\n", " "))

    #    batch_of_text = [str(p).strip() for p in batch_of_text if len(p.strip()) > 0]

    # batch_of_text_in_2 = split_in_2(batch_of_text)

    test_df = oral_history_data_loader.preprocess_data_for_test(real_dir, batch_of_text, word2id, id2word, 'test')

    test_df.to_pickle(real_dir.joinpath('test_df.pkl'))
    return batch_of_expected


if __name__ == '__main__':
    from pathlib import Path

    current_dir = Path(__file__).resolve().parent

    import configs

    config = configs.get_config()
    print(config)

    from build_utils import get_loader, build_model, get_ckpt_name

    expected = prepare_real_life_evaluation()

    # Build Data Loader
    data_dir = current_dir.joinpath(config.data + '_out')
    _, _, test_loader, word2id, id2word = get_loader(
        config, data_dir)

    # Build Model
    model = build_model(config, word2id, id2word)
    model.to(device)

    # Load Model from checkpoint
    # ckpt_dir = Path(f"./ckpt/{config.model}/").resolve()
    ckpt_dir = Path(f"./ckpt/{config.model}/").resolve()
    filename = get_ckpt_name(config)
    filename += f"_epoch{config.load_ckpt}.pkl"
    ckpt_path = ckpt_dir.joinpath(filename)
    ckpt = torch.load(ckpt_path,
                      map_location=device)  # TODO: remove this one #ckpt = torch.load(ckpt_path,map_location="cpu") if you bring the model locally
    model.load_state_dict(ckpt['model'])
    print('Loaded model from', ckpt_path)

    # Run Evaluation
    evaluate5(test_loader, model, config.load_ckpt, config, expected, test=True)
