
import altair
import hashlib
import json
import ollama
import pandas
import pathlib
import subprocess
import tqdm

def generate_checksum(filepath):

    """
    Generate MD5 hash from a file.
    """

    if not pathlib.Path(filepath).exists():
        raise Exception(f'{filepath} not found.')

    with open(filepath, "rb") as item:
        hash = hashlib.md5()
        for buff in iter(lambda: item.read(65536), b""):
            hash.update(buff)

        return hash.hexdigest().lower()

def extract_frames(path_in, path_out):

    """
    Use FFmpeg to extract frames from a video file.
    Note: granularity is set by the fps=1 arg.
    """

    if not path_out.exists():
        path_out.mkdir()

    subprocess.call([
        'ffmpeg',
        '-i', str(path_in),
        '-vf', 'scale=-2:720,fps=1', # one frame per second.
        #'-vf', 'scale=-2:720,fps=1/60', # one frame per minute.
        '-q:v', '2',
        f'{str(path_out)}/output_%04d.jpg'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def data_extract(img):

    """
    Route image and prompt to ollama api.
    """

    prompt = """
        You are an expert film cataloguer who is determining the likely
        time period or decade of a film based on the clothes and fashion
        evident in a single frame. If you have reasonable confidence please
        respond with JSON data, structured like {"epoch": "1940s"} or
        {"epoch": "1980s"}. There should be one key which should always be
        "epoch", and a decade expressed in the format "1850s", "1930s", "2010s",
        etc, or "don't know". If you are unsure return the response {"epoch": "don't know"}.
        You should only indicate a time period if you have a reasonable level
        of confidance based specifically on visible fashion of people in the
        frame. If no-one is visible in the frame you should respond {"epoch":
        "don't know"}.}
        Return the JSON data itself without commentary or code fence ('```').
        Do not return '```json' in the response."""

    r = ollama.chat(
        model="qwen3.8",
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [str(img)],
            }
        ],
    )

    result = r.message.content
    result = result.replace('```json','')
    result = result.replace('```','')

    return result

def validate_json(json_string):

    """
    Ensure that the response is valid json.
    """

    try:
        json.loads(json_string)
        return True
    except json.JSONDecodeError:
        return False

# check that ffmpeg is avilable.

subprocess.call(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# list of accepted responses from ollama.
# In theory people in early films could be legit wearing fashion from an earlier period,
# let alone intentional costuming for fictional purposes.

accepted_responses = [
    "1880s", "1890s", "1900s",  "1910s",
    "1920s", "1930s", "1940s", "1950s",
    "1960s", "1970s", "1980s", "1990s",
    "2000s", "2010s", "2020s", "don't know"
]

# parse incoming media files.

media_folder = pathlib.Path.cwd() / 'media'
media_files = [x for x in media_folder.iterdir() if x.suffix in ['.mp4', '.webm', '.mkv']]
for x in media_files:

    # use generated hash to route working folder.

    file_hash = generate_checksum(x)
    data_path = pathlib.Path.cwd() / 'data' / file_hash

    # extract frames. Note this does not well handle a failed ffmpeg process.

    if not data_path.exists():
        extract_frames(x, data_path)

    if not data_path.exists():
        raise Exception(f'{data_path} not found.')

    # process json to ollama.

    source_files = [i for i in data_path.iterdir() if i.suffix in ['.jpg']]
    for s in tqdm.tqdm(sorted(source_files)):
        json_path = s.with_suffix('.json')
        if json_path.exists():
            continue

        # currently infinite attempts at an accepted answer are allowed
        # you may want to cap a certain number of chances to prevent process getting stuck.

        run = 0
        while 1:
            run += 1
            r = data_extract(s)

            print('@', run, r)

            if not validate_json(r):
                continue
            elif (list(json.loads(r).keys()) != ['epoch']):
                continue
            elif json.loads(r)['epoch'] not in accepted_responses:
                continue
            else:
                break

        with open(json_path, 'w') as data_out:
            json.dump(json.loads(r), data_out, ensure_ascii=False, indent=4)

    # report one. pdf of frames and results.

    # TODO. It could be interesting to return a PDF of individual frames and ollama results at some point.
    # also a retrospective justification response could also be interesting,
    # although obviously not the original reasoning process.

    # report two. altair graph of results.

    png_path = pathlib.Path.cwd() / 'report' / f'{file_hash}.png'

    dataset = list()
    json_result = [j for j in data_path.iterdir() if j.suffix == '.json']
    for j in json_result:
        dataset.append(pandas.DataFrame([json.loads(j.read_text())]))

    df = pandas.concat(dataset, ignore_index=True)
    df = df['epoch'].value_counts().reset_index(name='count')

    df['perc'] = df['count'].apply(lambda x: x/sum(df['count']))
    chart = altair.Chart(df).mark_bar().encode(
        x=altair.X('perc', title=None),
        y=altair.Y('epoch', title=None),
        color=altair.Color('perc', scale=altair.Scale(scheme='lightgreyred'), title=None)
    ).properties(
        title=x.stem
    ).save(png_path)
