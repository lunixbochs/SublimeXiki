import sublime, sublime_plugin
from lib.util import communicate

import re

def xiki(view):
	settings = view.settings()

	if settings.get('xiki'):
		indent, tree = find_tree(view)
		if not tree: return
		print 'xiki', tree

		output = communicate(['xiki'] + tree.split(' '))
		output = output.rstrip('\r\n')
		if output:
			insert(view, output, indent + '\t')

def find_tree(view):
	view.run_command('single_selection')
	line = get_line(view)
	match = re.match('^(\s*)(\+ |- )?(.*)$', line)
	line_indent = last_indent = match.group(1)
	tag = match.group(3)
	tree = [tag]

	offset = -1
	while last_indent != '':
		print repr(last_indent), line
		line = get_line(view, offset)
		offset -= 1

		match = re.match('^(\s*)(\+ |- )?(.*)$', line)
		if match:
			indent = match.group(1)
			tag = match.group(3)

			if len(indent) < len(last_indent) and tag:
				last_indent = indent
				tree.insert(0, tag.strip('/'))

	new_tree = []
	for tag in reversed(tree):
		if tag.startswith('@'):
			new_tree.insert(0, tag.strip('@'))
			break

		new_tree.insert(0, tag)

	return line_indent, '/'.join(new_tree)

# helpers

def cleanup(view, edit, pos, indent):
	line, _ = view.rowcol(pos)

	while True:
		point = view.text_point(line + 1, 0)
		region = view.full_line(point)
		if region.a == region.b:
			return

		text = view.substr(region)
		if not text.strip() or text.startswith(indent):
			view.erase(edit, region)
		else:
			break

def insert(view, text, indent=''):
	cursor = view.sel()[0].b
	line_end = view.line(cursor).b

	edit = view.begin_edit()
	cleanup(view, edit, line_end, indent)

	view.insert(edit, line_end, '\n')
	for line in reversed(text.split('\n')):
		view.insert(edit, line_end, '\n' + indent + line)

	view.sel().clear()
	view.sel().add(sublime.Region(line_end, line_end))
	view.end_edit(edit)

def get_line(view, offset=0):
	sel = view.sel()
	point = sel[0].b
	row, _ = view.rowcol(point)

	point = view.text_point(row + offset, 0)	
	if row + offset < 0:
		print point, row + offset
		raise Exception

	line = view.line(point)
	return view.substr(line).strip('\r\n')

# sublime commands`

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
		view.settings().set('xiki', True)

class XikiClick(sublime_plugin.WindowCommand):
	def run(self):
		view = self.window.active_view()
		if view.settings().get('xiki'):
			xiki(view)
		else:
			# emulate the default double-click behavior
			# if we're not in a xiki buffer
			view.run_command('expand_selection', {'to': 'word'})
