import sublime, sublime_plugin

import lib.util
import sys
# reload lib.util on update/reload of primary module
# so improvements will be loaded without a sublime restart
sys.modules['lib.util'] = reload(lib.util)
from lib.util import communicate, which, popen

import os
import re
import shlex

import subprocess
import thread
import time
import traceback
import Queue

INDENTATION = '  '

class BoundaryError(Exception): pass

if not 'already' in globals():
	already = True
	commands = {}

def spawn(view, edit, indent, cmd, sel):
	q = Queue.Queue()
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

	def merge(region, count):
		if q.empty(): return
		regions = view.get_regions(region)
		if not regions: return

		pos = view.line(regions[0].end() - 1)
		edit = view.begin_edit()
		try:
			start = time.time()
			lines = []
			while start - time.time() < 0.05:
				try:
					lines.append(q.get(False))
					q.task_done()
					count += 1
				except Queue.Empty:
					break

			if not lines: return
			insert(view, edit, pos, '\n'.join(lines), indent + INDENTATION)

			fold(region)
		except:
			print traceback.format_exc()
		finally:
			view.end_edit(edit)

	def poll(p, region, fd):
		count = 0
		while p.poll() is None:
			line = fd.readline()
			if line:
				q.put(line.rstrip('\r\n'))
				sublime.set_timeout(make_callback(merge, region, count), 100)

			if count % 3 == 0:
				time.sleep(0.01)

		# if the process wasn't terminated
		if p.returncode >= 0:
			out = fd.read()
			if out:
				q.put(out.rstrip('\r\n'))
				sublime.set_timeout(make_callback(merge, region, count), 100)

	def stderr(p, region):
		poll(p, region, p.stderr)

	def stdout(p, region):
		poll(p, region, p.stdout)

		sublime.set_timeout(make_callback(view.erase_regions, region), 500)
		del commands[region]
		return

	p = popen(cmd, return_error=True)
	if isinstance(p, subprocess.Popen):
		region = 'xiki sub %i' % p.pid
		line = view.full_line(sel.b)
		spread = sublime.Region(line.a, line.b)
		commands[region] = p
		view.add_regions(region, [spread], 'keyword', '', sublime.DRAW_OUTLINED)

		thread.start_new_thread(stdout, (p, region))
		thread.start_new_thread(stderr, (p, region))
	else:
		insert(view, edit, sel, 'Error: ' + p, indent + INDENTATION)

def xiki(view):
	settings = view.settings()

	if settings.get('xiki'):
		for sel in view.sel():
			output = None
			cmd = None
			persist = False
			oldcwd = None

			view.sel().subtract(sel)
			edit = view.begin_edit()

			row, _ = view.rowcol(sel.b)
			indent, sign, path, tag, tree = find_tree(view, row)

			pos = view.line(sel.b).b
			if get_line(view, row+1).startswith(indent + INDENTATION):
				if sign == '-':
					replace_line(view, edit, pos, indent + '+ ' + tag)

				do_clean = True
				check = sublime.Region(sel.b, sel.b)
				for name, process in commands.items():
					regions = view.get_regions(name)
					for region in regions:
						if region.contains(check):
							process.terminate()
							do_clean = False

				if do_clean:
					cleanup(view, edit, pos, indent + INDENTATION)
				# select(view, pos)
			elif sign == '$':
				if path:
					p = dirname(path, tree, tag)

					oldcwd = os.getcwd()
					os.chdir(p)

				try:
					cmd = shlex.split(tag.encode('ascii', 'replace'), True)
				except ValueError, err:
					output = 'Error: ' + str(err)

				persist = True
			elif path:
				# directory listing or file open
				target = os.path.join(path, tree)
				d, f = os.path.split(target)
				f = unslash(f)
				target = os.path.join(d, f)

				if os.path.isfile(target):
					sublime.active_window().open_file(target)
				elif os.path.isdir(target):
					dirs = ''
					files = ''
					listing = []
					try:
						listing = os.listdir(target)
					except OSError, err:
						dirs = '- ' + err.strerror + '\n'

					for entry in listing:
						absolute = os.path.join(target, entry)
						if os.path.isdir(absolute):
							dirs += '+ %s/\n' % entry
						else:
							entry = slash(entry, '\\+$-')
							files += '%s\n' % entry

					output = (dirs + files) or '\n'
			elif sign == '-':
				# dunno here
				pass
			elif tree:
				if which('ruby'):
					cmd = ['ruby', which('xiki')]
				else:
					cmd = ['xiki']

				cmd += tree.split(' ')

			if cmd:
				if persist:
					insert(view, edit, sel, '', indent + INDENTATION)
					spawn(view, edit, indent, cmd, sel)
				else:
					output = communicate(cmd, None, 3, return_error=True)

				if oldcwd:
					os.chdir(oldcwd)

			if output:
				if sign == '+':
					replace_line(view, edit, pos, indent + '- ' + tag)

				insert(view, edit, sel, output, indent + INDENTATION)

			view.sel().add(sel)
			view.end_edit(edit)

def find_tree(view, row):
	regex = re.compile(r'^(\s*)([-+$]\s*)?(.*)$')

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
		elif part.startswith('/'):
			path = part
		elif part.startswith('~'):
			path = os.path.expanduser(part)
		else:
			new_tree.insert(0, part)
			continue

		break

	return line_indent, sign, path, tag, '/'.join(new_tree).replace('//', '/')

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

	view.insert(edit, line.b, text + '\n')
	view.erase(edit, line)

def cleanup(view, edit, pos, indent):
	line, _ = view.rowcol(pos)

	while True:
		point = view.text_point(line + 1, 0)
		region = view.full_line(point)
		if region.a == region.b:
			break

		text = view.substr(region)
		if text.startswith(indent):
			view.erase(edit, region)
		else:
			break

def insert(view, edit, sel, text, indent=''):
	line_end = view.line(sel.b).b

	# TODO: does it always make sense to cleanup here?
	# I bet it's way slower for console scrolling.
	cleanup(view, edit, line_end, indent)

	for line in reversed(text.split('\n')):
		line = '\n' + indent + line
		view.insert(edit, line_end, line.encode('ascii', 'replace'))

def get_line(view, row=0):
	point = view.text_point(row, 0)
	if row < 0:
		raise BoundaryError

	line = view.line(point)
	return view.substr(line).strip('\r\n')

def dirname(path, tree, tag):
	path_re = r'^(.+)/%s$' % re.escape(tag)
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
					ret.append(name)

		return ret

def make_callback(func, *args, **kwargs):
	def wrapper():
		return func(*args, **kwargs)

	return wrapper

# sublime event classes

class XikiComplete(sublime_plugin.EventListener):
	def on_query_completions(self, view, prefix, locations):
		if view.settings().get('xiki'):
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
					return completions(target, partial)

class Xiki(sublime_plugin.WindowCommand):
	def run(self):
		view = self.window.active_view()
		xiki(view)

	def is_enabled(self):
		view = self.window.active_view()
		if view.settings().get('xiki'):
			return True

class NewXiki(sublime_plugin.WindowCommand):
	def run(self):
		view = self.window.new_file()
		settings = view.settings()

		settings.set('xiki', True)
		settings.set('tab_size', 2)
		settings.set('translate_tabs_to_spaces', True)
		settings.set('syntax', 'Packages/SublimeXiki/Xiki.tmLanguage')

class XikiClick(sublime_plugin.WindowCommand):
	def run(self):
		view = self.window.active_view()
		if view.settings().get('xiki'):
			xiki(view)
		else:
			# emulate the default double-click behavior
			# if we're not in a xiki buffer
			view.run_command('expand_selection', {'to': 'word'})
