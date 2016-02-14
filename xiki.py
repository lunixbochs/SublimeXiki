import sublime, sublime_plugin

import sys
import os

from .lib import util
from .edit import Edit

from collections import defaultdict
import json
import platform
import queue
import re
import shlex
import subprocess
import _thread
import time
import traceback

INDENTATION = '  '
backspace_re = re.compile('.\b')

xiki_settings = sublime.load_settings('SublimeXiki.sublime-settings')

class BoundaryError(Exception): pass

if not 'already' in globals():
    already = True
    commands = defaultdict(dict)

def spawn(view, indent, cmd, sel):
    local_commands = commands[view.id()]
    q = queue.Queue()
    def fold(region):
        regions = view.get_regions(region)
        for region in regions:
            lines = view.split_by_newlines(region)
            if len(lines) > 24:

                lines = lines[1:-24]
                try:
                    area = lines.pop()
                except IndexError:
                    return

                for sub in lines:
                    area = area.cover(sub)

                view.unfold(area)
                view.fold(area)

    def merge(region):
        if q.empty(): return
        regions = view.get_regions(region)
        if not regions: return

        pos = view.line(regions[0].end() - 1)

        restore_sel = []
        for sel in view.sel():
            if pos.end() in (sel.a, sel.b):
                restore_sel.append(sel)
                view.sel().subtract(sel)

        with Edit(view) as edit:
            try:
                start = time.time()
                lines = []
                while time.time() - start < 0.05 and len(lines) < 200:
                    try:
                        lines.append(q.get(False))
                        q.task_done()
                    except queue.Empty:
                        break

                if not lines: return
                lines = backspace_re.sub('', '\n'.join(lines))
                insert(view, edit, pos, lines, indent + INDENTATION)

                fold(region)
            except:
                print(traceback.format_exc())
            finally:
                def restore_selections():
                    for sel in restore_sel:
                        view.sel().add(sel)

                edit.callback(restore_selections)

    def poll(p, region, fd):
        line = True
        while p.poll() is None or line:
            line = fd.readline()
            if isinstance(line, bytes):
                line = line.decode('utf8')

            if line:
                q.put(line.rstrip('\r\n'))

        # if the process wasn't terminated
        out = fd.read()
        if isinstance(out, bytes):
            out = out.decode('utf8')

        if out:
            q.put(out.rstrip('\r\n'))
            merge(region)

    def out(p, region):
        last = 0
        while p.poll() is None:
            since = time.time() - last
            if since > 0.05 or since > 0.01 and q.qsize() < 10:
                last = time.time()
                merge(region)
            else:
                time.sleep(max(0.1 - since, 0.1))

        if p.returncode not in (-9, -15):
            del local_commands[region]
            while not q.empty():
                merge(region)
                time.sleep(0.05)

        view.erase_regions(region)

    p = util.popen(cmd, use_pty=False)
    if isinstance(p, subprocess.Popen):
        region = 'xiki sub %i' % p.pid
        line = view.full_line(sel.b)
        spread = sublime.Region(line.a, line.b)
        local_commands[region] = p
        view.add_regions(region, [spread], 'keyword', '', sublime.DRAW_OUTLINED)

        if p.pty:
            _thread.start_new_thread(poll, (p, region, p.stdout))
        else:
            _thread.start_new_thread(poll, (p, region, p.stderr))
            _thread.start_new_thread(poll, (p, region, p.stdout))
        _thread.start_new_thread(out, (p, region))
    else:
        with Edit(view) as edit:
            insert(view, edit, sel, 'Error: ' + (p or ''), indent + INDENTATION)

def xiki(view, cont=False):
    if is_xiki_buffer(view):
        for sel in view.sel():
            output = None
            cmd = None
            persist = False
            oldcwd = None
            op = None
            scroll = False
            windows = platform.system() == 'Windows'

            view.sel().subtract(sel)

            if sel.end() == view.size():
                with Edit(view) as edit:
                    edit.insert(view.size(), '\n')

            row, _ = view.rowcol(sel.b)
            indent, sign, path, tag, tree = find_tree(view, row)

            pos = view.line(sel.b).b
            if get_line(view, row+1).startswith(indent + INDENTATION):
                if sign == '-':
                    with Edit(view) as edit:
                        replace_line(view, edit, pos, indent + '+ ' + tag)

                do_clean = True
                check = sublime.Region(sel.b, sel.b)
                for name, process in list(commands[view.id()].items()):
                    regions = view.get_regions(name)
                    for region in regions:
                        if region.contains(check):
                            try:
                                process.terminate()
                            except OSError:
                                pass

                            do_clean = False

                if do_clean and not cont:
                    op = 'cleanup'
                    with Edit(view) as edit:
                        cleanup(view, edit, pos, indent + INDENTATION)
                # select(view, pos)
            elif sign == '$' or sign == '$$':
                op = 'command'
                error = None

                p = os.path.expanduser('~')
                if path:
                    p = dirname(path, tree, tag)
                    if windows:
                        p = p.lstrip('/')
                try:
                    oldcwd = os.getcwd()
                except FileNotFoundError:
                    pass
                try:
                    os.chdir(p)
                except Exception as err:
                    error = err

                env = util.create_environment()
                shell = env.get('SHELL')
                if shell and util.which(shell):
                    cmd = [shell, '-c', tag]
                elif windows:
                    cmd = ['cmd', '/c', tag]
                if not cmd:
                    try:
                        cmd = shlex.split(tag, True)
                    except ValueError as err:
                        error = err

                if error:
                    cmd = None
                    output = str(error) + '\n'

                persist = True
            elif path:
                # directory listing or file open
                target = os.path.join(path, tree)
                d, f = os.path.split(target)
                f = unslash(f)
                target = os.path.join(d, f)

                if os.path.isfile(target):
                    op = 'file'
                    if windows:
                        target = os.path.abspath(target)

                    if not cont:
                        sublime.active_window().open_file(target)
                elif os.path.isdir(target):
                    op = 'dir'
                    dirs = ''
                    files = ''
                    listing = []
                    try:
                        if windows and target == '/':
                            listing = [drive + ':' for drive in util.get_windows_drives()]
                        else:
                            listing = os.listdir(target)
                    except OSError as err:
                        dirs = '- ' + err.strerror + '\n'

                    if windows and target.startswith('/'):
                        target = target.lstrip('/')

                    for entry in listing:
                        absolute = os.path.join(target, entry)
                        if os.path.isdir(absolute):
                            dirs += '+ %s%s\n' % (entry, os.sep)
                        else:
                            entry = slash(entry, '\\+$-')
                            files += '%s\n' % entry

                    output = (dirs + files) or ' '
            elif sign == '-':
                # dunno here
                pass
            elif tree:
                op = 'xiki'
                cmd = ['xiki']
                cmd += tree.split(' ')

            if cmd:
                if persist:
                    end = view.line(sel.b).b
                    with Edit(view) as edit:
                        edit.insert(end, '\n' + indent + INDENTATION)
                    spawn(view, indent, cmd, sel)
                else:
                    output = util.communicate(cmd, None, 3)

                if oldcwd:
                    os.chdir(oldcwd)

            if output:
                with Edit(view) as edit:
                    if sign == '+':
                        replace_line(view, edit, pos, indent + '- ' + tag)

                    insert(view, edit, sel, output, indent + INDENTATION)

            if cont:
                region = find_region(view, pos, indent + INDENTATION)
                end = view.line(region.end()).begin()

                added = ''
                if op == 'file':
                    added += '$ '
                elif op == 'dir':
                    added += INDENTATION + '$ '
                elif sign == '$':
                    added += sign + ' '

                def set_selection():
                    cur = view.line(end).end()
                    sel = sublime.Region(cur, cur)
                    view.sel().add(sel)
                    view.show_at_center(sel)

                with Edit(view) as edit:
                    edit.insert(end, indent + added + '\n')
                    edit.callback(set_selection)
            else:
                view.sel().add(sel)

            if scroll:
                view.show_at_center(sel)

def find_tree(view, row):
    regex = re.compile(r'^(\s*)(\$\$|[-+$]\s*)?(.*)$')

    line = get_line(view, row)
    match = regex.match(line)

    line_indent = last_indent = match.group(1)
    sign = (match.group(2) or '').strip()
    tag = match.group(3)
    tree = [tag]
    if tag.startswith('/'):
        sign = '/'

    offset = -1
    while last_indent != '':
        try:
            line = get_line(view, row+offset)
        except BoundaryError:
            break

        offset -= 1

        match = regex.match(line)
        if match:
            indent = match.group(1)
            part = match.group(3)

            if len(indent) < len(last_indent) and part:
                last_indent = indent
                tree.insert(0, part)

    new_tree = []
    path = None
    for part in reversed(tree):
        if part.startswith('@'):
            new_tree.insert(0, part.strip('@'))
        elif part.startswith(('/', os.sep)):
            path = part
        elif re.match(r'^[A-Z]:\\', part):
            path = part
        elif part.startswith('~'):
            path = os.path.expanduser(part)
        else:
            new_tree.insert(0, part)
            continue

        break

    return line_indent, sign, path, tag, os.sep.join(new_tree).replace(os.sep * 2, os.sep)

# helpers

def slash(s, chars):
    if re.match(r'^[%s]' % re.escape(chars), s):
        s = '\\' + s

    return s

def unslash(s):
    out = ''
    escaped = False
    for c in s:
        if escaped:
            escaped = False
            out += c
        elif c == '\\':
            escaped = True
        else:
            out += c

    return out

def replace_line(view, edit, point, text):
    text = text.rstrip()
    line = view.full_line(point)

    edit.insert(line.b, text + '\n')
    edit.erase(line)

def find_region(view, pos, indent):
    line, _ = view.rowcol(pos)

    point = view.text_point(line + 1, 0)
    text = view.substr(sublime.Region(point, view.size()))
    count = 0
    for l in text.split('\n'):
        if not l.startswith(indent) and l.strip():
            break
        else:
            count += 1

    start = view.text_point(line + 1, 0)
    end = view.text_point(line + count, 0)
    region = sublime.Region(
        view.full_line(start).begin(),
        view.full_line(end).end(),
    )
    return region

def cleanup(view, edit, pos, indent):
    region = find_region(view, pos, indent)
    edit.erase(region)

def insert(view, edit, sel, text, indent='', cleanup=True):
    pos = view.line(sel.b).b

    lines = reversed(text.split('\n'))
    for line in lines:
        line = '\n' + indent + line
        edit.insert(pos, line)

def get_line(view, row=0):
    point = view.text_point(row, 0)
    if row < 0:
        raise BoundaryError

    line = view.line(point)
    return view.substr(line).strip('\r\n')

def dirname(path, tree, tag):
    path_re = r'^(.+)%s%s$' % (re.escape(os.sep), re.escape(tag))
    match = re.match(path_re, tree)
    if match:
        return os.path.join(path, match.group(1))
    else:
        return path

def completions(base, partial, executable=False):
    if os.path.isdir(base):
        ret = []
        partial = partial.lower()

        for name in os.listdir(base):
            path = os.path.join(base, name)
            if name.lower().startswith(partial):
                if not executable or os.access(path, os.X_OK):
                    ret.append((name, name))

        return ret

def apply_xiki_settings(view):
    settings = view.settings()
    settings.set('tab_size', 2)
    settings.set('translate_tabs_to_spaces', True)
    settings.set('syntax', 'Packages/SublimeXiki/Xiki.tmLanguage')

def is_xiki_buffer(view):
    if view is None or not view.settings().has('syntax'):
        return False

    return view.settings().get('syntax').endswith('/Xiki.tmLanguage')

# sublime event classes

class XikiListener(sublime_plugin.EventListener):
    def on_query_completions(self, view, prefix, locations):
        if is_xiki_buffer(view):
            sel = view.sel()
            if len(sel) == 1:
                row, _ = view.rowcol(sel[0].b)
                indent, sign, path, tag, tree = find_tree(view, row)

                if sign == '$':
                    # command completion
                    pass
                elif path:
                    # directory/file completion
                    target, partial = os.path.split(dirname(path, tree, tag))
                    return completions(target, partial), sublime.INHIBIT_WORD_COMPLETIONS

    def on_query_context(self, view, key, operator, operand, match_all):
        if key == 'xiki' and is_xiki_buffer(view):
            return True

    def on_load(self, view):
        # handle new user preferences file
        if view.file_name() and os.path.split(view.file_name())[1] == 'SublimeXiki.sublime-settings':
            if view.size() == 0:
                with Edit(view) as edit:
                    template = {
                        "double_click": False,
                    }
                    edit.insert(0, json.dumps(template, indent=4))
        elif is_xiki_buffer(view):
            apply_xiki_settings(view)

    def on_close(self, view):
        vid = view.id()
        for process in list(commands[vid].values()):
            try:
                process.terminate()
            except OSError:
                pass

        del commands[vid]

class Xiki(sublime_plugin.TextCommand):
    def run(self, edit):
        xiki(self.view)

    def is_enabled(self):
        if is_xiki_buffer(self.view):
            return True
        return False

class XikiContinue(Xiki):
    def run(self, edit):
        xiki(self.view, cont=True)

class NewXiki(sublime_plugin.WindowCommand):
    def run(self):
        view = self.window.new_file()
        apply_xiki_settings(view)

class XikiClick(sublime_plugin.WindowCommand):
    def run(self):
        view = self.window.active_view()
        if is_xiki_buffer(view) and xiki_settings.get('double_click'):
            sel = view.sel()
            s = sel[0]

            text = view.substr(s)
            is_word = r'^(\w+|[^\w]+)$'
            if not re.match(is_word, text.strip('\n')):
                return

            sel.clear()
            sel.add(sublime.Region(s.b, s.a))
            xiki(view)
