import pandas as pd

df = pd.read_pickle("oh/01_input.pkl")
Text = list(df.Text.values)
Summary = list(df.Summary.values)

test_text = Text[:500]
test_summary = Summary[:500]

validation_text = Text[500:1000]
validation_summary = Summary[500:1000]

train_text = Text[1000:]
train_summary = Summary[1000:]


train = pd.DataFrame({"Text":train_text,"Summary":train_summary})

test = pd.DataFrame({"Text":test_text,"Summary":test_summary})


val = pd.DataFrame({"Text":validation_text,"Summary":validation_summary})

train.to_pickle("oh/train.pkl")

test.to_pickle("oh/test.pkl")

val.to_pickle("oh/val.pkl")