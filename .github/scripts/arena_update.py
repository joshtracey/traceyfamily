"""Apply a submitted arena form (a GitHub issue) to the Arena Streaming Guide.

Run by .github/workflows/arena-updates.yml when someone fills in one of the
forms in .github/ISSUE_TEMPLATE. Updates from collaborators go straight in;
anyone else's wait until a maintainer adds the "approved" label.
"""
import json
import os
import re
import subprocess
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

RINKS = 'arenas/_rinks'
PHOTOS = 'arenas/photos'
TEMPLATE = 'arenas/_includes/arena-template.md'
TRUSTED = {'OWNER', 'MEMBER', 'COLLABORATOR'}
MAX_PHOTO = 15 * 1024 * 1024

RECEPTION = {'Good': 'Good', 'OK': 'OK', 'Poor': 'Poor', 'No signal': 'None', 'Unknown': 'Unknown'}
YES_NO = {'Yes': 'Yes', 'No': 'No', 'Unknown': 'Unknown'}

# Form questions by their labels in .github/ISSUE_TEMPLATE, so keep the two in
# step. Dropdowns can't offer "None" or "N/A" as answers, so the forms say
# "No signal" and so on, and these map them back. "No change" isn't mapped,
# which leaves the field alone.
CHOICES = {
    'Arena stream': ('arena_stream', {'LiveBarn': 'LiveBarn', 'Hudl': 'Hudl', 'Other': 'Other',
                                      'No arena stream': 'None', 'Unknown': 'Unknown'}),
    'Bell / Telus cell': ('cell_bell_telus', RECEPTION),
    'Rogers cell': ('cell_rogers', RECEPTION),
    'WiFi': ('wifi', YES_NO),
    'WiFi welcome page': ('captive_portal', {'Yes': 'Yes', 'No': 'No', 'No WiFi here': 'N/A', 'Unknown': 'Unknown'}),
    'WiFi blocks streaming': ('blocks_streaming', {'Yes': 'Yes', 'No': 'No', 'Partly': 'Partial', 'Unknown': 'Unknown'}),
    'Ethernet port': ('ethernet', YES_NO),
}
TEXT = {
    'Arena stream link': 'arena_stream_link',
    'Where the Ethernet port is': 'ethernet_location',
    'Best camera spot': 'best_camera_spot',
}
TIPS = ('Tips to add', 'Tips')

IMAGE_MD = re.compile(r'!\[([^\]]*)\]\((https://[^)\s]+)\)')
IMAGE_TAG = re.compile(r'<img\b[^>]*>', re.I)
ATTACHMENT = re.compile(r'https://(github\.com/user-attachments/assets/|(private-)?user-images\.githubusercontent\.com/)')
PHOTO_TYPES = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif', 'image/webp': 'webp'}
YAML_WORDS = {'yes', 'no', 'y', 'n', 'true', 'false', 'on', 'off', 'null', '~'}


class FormProblem(Exception):
    """Something in the form that needs a person to sort out."""


def parse_form(body):
    """Issue forms arrive as '### Question' headings, each followed by its answer."""
    answers, label = {}, None
    for line in (body or '').replace('\r\n', '\n').split('\n'):
        # Tips come last and may have headings of their own, so stop splitting there.
        if line.startswith('### ') and label not in TIPS:
            label = line[4:].strip()
            answers[label] = []
        elif label is not None:
            answers[label].append(line)
    answers = {k: '\n'.join(v).strip() for k, v in answers.items()}
    return {k: '' if v == '_No response_' else v for k, v in answers.items()}


def one_line(text):
    return ' '.join(text.split())[:200]


def yaml_value(text):
    """Plain where that's safe, otherwise double-quoted (a JSON string is valid YAML)."""
    if re.fullmatch(r"[A-Za-z0-9À-ſ][A-Za-z0-9À-ſ .,'()&/-]*", text) \
            and text.lower() not in YAML_WORDS:
        return text
    return json.dumps(text, ensure_ascii=False)


def slugify(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def today():
    return datetime.now(ZoneInfo('America/Moncton')).strftime('%Y-%m-%d')


def split_page(text):
    match = re.match(r'---\n(.*?\n)---\n?(.*)\Z', text, re.S)
    if not match:
        raise FormProblem('The arena page file is not in the usual format.')
    return match.group(1), match.group(2)


def join_page(front, body):
    body = body.strip()
    return f'---\n{front}---\n' + (f'\n{body}\n' if body else '')


def get_field(front, key):
    match = re.search(rf'^{re.escape(key)}:(.*)$', front, re.M)
    value = match.group(1).strip() if match else ''
    if value.startswith('"'):
        value = json.loads(value)
    return value.strip("'")


def set_field(front, key, value):
    line = f'{key}: {value}'
    pattern = re.compile(rf'^{re.escape(key)}:.*$', re.M)
    if pattern.search(front):
        return pattern.sub(lambda _: line, front, count=1)
    return front + line + '\n'


def apply_answers(front, answers):
    """Write the form's answers into the front matter. Returns it and whether anything changed."""
    changed = False
    for label, (key, options) in CHOICES.items():
        value = options.get(answers.get(label, ''))
        if value and value.lower() != get_field(front, key).lower():
            front = set_field(front, key, value)
            changed = True
    for label, key in TEXT.items():
        text = one_line(answers.get(label, ''))
        if text and key == 'arena_stream_link' and not re.match(r'https?://', text):
            text = 'https://' + text
        if text and text != get_field(front, key):
            front = set_field(front, key, yaml_value(text))
            changed = True
    return front, changed


def fetch_image(url):
    """The photo's bytes and file extension, or None if it can't be kept."""
    request = urllib.request.Request(url, headers={'User-Agent': 'arena-updates'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            ext = PHOTO_TYPES.get(response.headers.get_content_type())
            data = response.read(MAX_PHOTO + 1)
    except (OSError, ValueError) as e:
        print(f'Could not download {url}: {e}')
        return None
    if not ext or len(data) > MAX_PHOTO:
        return None
    return data, ext


def save_photos(tips, slug, number):
    """Copy photos attached to the form into the site, so they don't rely on GitHub's links."""
    saved = []

    def keep(alt, url):
        got = fetch_image(url) if ATTACHMENT.match(url) else None
        if not got:
            return None
        data, ext = got
        path = f'{PHOTOS}/{slug}-{number}-{len(saved) + 1}.{ext}'
        os.makedirs(PHOTOS, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
        saved.append(path)
        return f'![{alt.strip() or "Photo"}](/{path})'

    def from_markdown(m):
        return keep(m.group(1), m.group(2)) or m.group(0)

    def from_tag(m):
        src = re.search(r'src="([^"]+)"', m.group(0))
        alt = re.search(r'alt="([^"]*)"', m.group(0))
        return (src and keep(alt.group(1) if alt else '', src.group(1))) or m.group(0)

    tips = IMAGE_MD.sub(from_markdown, tips)
    tips = IMAGE_TAG.sub(from_tag, tips)
    return tips, saved


def update_arena(answers, number):
    slug = answers.get('Arena', '').strip().lower()
    path = f'{RINKS}/{slug}.md'
    if not re.fullmatch(r'[a-z0-9-]+', slug) or not os.path.isfile(path):
        raise FormProblem(f'There is no arena page called "{slug}".')
    with open(path, encoding='utf-8') as f:
        front, body = split_page(f.read())
    front, changed = apply_answers(front, answers)
    tips, photos = save_photos(answers.get('Tips to add', ''), slug, number)
    if not changed and not tips:
        return None
    front = set_field(front, 'last_updated', today())
    if tips:
        body = body.strip() + '\n\n' + tips
    with open(path, 'w', encoding='utf-8') as f:
        f.write(join_page(front, body))
    name = get_field(front, 'name') or slug
    return f'Update {name} from #{number}', [path] + photos, slug, name, 'updated'


def add_arena(answers, number):
    name = one_line(answers.get('Arena name', ''))
    slug = slugify(name)
    if not slug:
        raise FormProblem('The form needs the arena\'s name.')
    path = f'{RINKS}/{slug}.md'
    if os.path.exists(path):
        raise FormProblem(f'There is already a page for {name}: {site_url(slug)} '
                          'If it\'s the same rink, please use Add notes on that page instead.')
    with open(TEMPLATE, encoding='utf-8') as f:
        front, _ = split_page(f.read())
    front = set_field(front, 'name', yaml_value(name))
    for label, key in (('Town or city', 'city'), ('Street address', 'address')):
        text = one_line(answers.get(label, ''))
        if text:
            front = set_field(front, key, yaml_value(text))
    front, _ = apply_answers(front, answers)
    front = set_field(front, 'last_updated', today())
    tips, photos = save_photos(answers.get('Tips', ''), slug, number)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(join_page(front, tips))
    return f'Add {name} from #{number}', [path] + photos, slug, name, 'added'


def git(*args):
    subprocess.run(['git', *args], check=True)


def commit(paths, message, author):
    credit = f"Co-authored-by: {author['login']} <{author['id']}+{author['login']}@users.noreply.github.com>"
    git('config', 'user.name', 'github-actions[bot]')
    git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    git('add', '--', *paths)
    git('commit', '-m', message, '-m', credit)
    for _ in range(3):
        if subprocess.run(['git', 'push', 'origin', 'HEAD:main']).returncode == 0:
            return
        git('pull', '--rebase', 'origin', 'main')
    raise SystemExit('Could not push the update.')


def api(method, path, data=None):
    url = os.environ.get('GITHUB_API_URL', 'https://api.github.com') + path
    request = urllib.request.Request(url, method=method, headers={
        'Authorization': f"Bearer {os.environ['GH_TOKEN']}",
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }, data=None if data is None else json.dumps(data).encode())
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def issue_path(number):
    return f"/repos/{os.environ['GITHUB_REPOSITORY']}/issues/{number}"


def comment(number, text):
    api('POST', issue_path(number) + '/comments', {'body': text})


def close(number, reason):
    api('PATCH', issue_path(number), {'state': 'closed', 'state_reason': reason})


def site_url(slug):
    with open('CNAME') as f:
        return f'https://{f.read().strip()}/arenas/{slug}/'


def main():
    with open(os.environ['GITHUB_EVENT_PATH']) as f:
        event = json.load(f)
    issue = event['issue']
    number = issue['number']

    # Only people with triage access can add labels, so "approved" is a maintainer's say-so.
    if event['action'] == 'opened' and issue.get('author_association') not in TRUSTED:
        comment(number, 'Thanks for adding to the guide! Updates from new contributors are '
                        'checked before they go live, so this will be published once it\'s approved.')
        return

    answers = parse_form(issue.get('body'))
    try:
        result = add_arena(answers, number) if 'Arena name' in answers else update_arena(answers, number)
    except FormProblem as e:
        comment(number, f'{e}\n\nA maintainer can fix the form and add the `approved` label to try again.')
        return
    if result is None:
        comment(number, 'Nothing to update: every question was left on "No change" and no tips were added.')
        close(number, 'not_planned')
        return

    message, paths, slug, name, verb = result
    commit(paths, message, issue['user'])
    # Pushes made by the workflow's own token may not start a Pages build, so ask for one.
    try:
        api('POST', f"/repos/{os.environ['GITHUB_REPOSITORY']}/pages/builds")
    except urllib.error.HTTPError as e:
        print(f'Pages build request failed: {e}')
    comment(number, f'Thanks! {name} is {verb}. It will be live at {site_url(slug)} in a minute or two.')
    close(number, 'completed')


if __name__ == '__main__':
    main()
