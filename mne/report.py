"""Generate html report from MNE database
"""

# Authors: Alex Gramfort <alexandre.gramfort@telecom-paristech.fr>
#          Mainak Jas <mainak@neuro.hut.fi>
#
# License: BSD (3-clause)

import os
import os.path as op
import fnmatch
import re
import StringIO
import numpy as np
import time
from glob import glob
import webbrowser

from . import read_evokeds, read_events, Covariance
from .io import Raw, read_info
from .utils import _TempDir
from .viz import plot_events, _plot_mri_contours, plot_trans
from .forward import read_forward_solution

from tempita import HTMLTemplate, Template

tempdir = _TempDir()

###############################################################################
# IMAGE FUNCTIONS


def _build_image(data, dpi=1, cmap='gray'):
    """ Build an image encoded in base64 """

    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas

    figsize = data.shape[::-1]
    if figsize[0] == 1:
        figsize = tuple(figsize[1:])
        data = data[:, :, 0]
    fig = Figure(figsize=figsize, dpi=dpi, frameon=False)
    FigureCanvas(fig)
    cmap = getattr(plt.cm, cmap, plt.cm.gray)
    fig.figimage(data, cmap=cmap)
    output = StringIO.StringIO()
    fig.savefig(output, dpi=dpi, format='png')
    return output.getvalue().encode('base64')


def iterate_sagittal_slices(array, limits=None):
    """ Iterate sagittal slice """
    shape = array.shape[0]
    for ind in xrange(shape):
        if limits and ind not in limits:
            continue
        yield ind, np.rot90(array[ind, :, :])


def iterate_coronal_slices(array, limits=None):
    """ Iterate coronal slice """
    shape = array.shape[1]
    for ind in xrange(shape):
        if limits and ind not in limits:
            continue
        yield ind, np.rot90(array[:, ind, :])


def iterate_axial_slices(array, limits=None):
    """ Iterate axial slice """
    shape = array.shape[2]
    for ind in xrange(shape):
        if limits and ind not in limits:
            continue
        yield ind, np.rot90(array[:, :, ind])


###############################################################################
# HTML functions

def build_html_image(img, id, div_klass, img_klass, caption=None, show=True):
    """ Build a html image from a slice array """
    html = []
    add_style = '' if show else 'style="display: none"'
    html.append(u'<li class="%s" id="%s" %s>' % (div_klass, id, add_style))
    html.append(u'<div class="thumbnail">')
    html.append(u'<img class="%s" alt="" style="width:90%%;" '
                'src="data:image/png;base64,%s">'
                % (img_klass, img))
    html.append(u'</div>')
    if caption:
        html.append(u'<h4>%s</h4>' % caption)
    html.append(u'</li>')
    return '\n'.join(html)

slider_template = HTMLTemplate(u"""
<div id="{{slider_id}}"></div>
<script>$("#{{slider_id}}").slider({
                       range: "min",
                       /*orientation: "vertical",*/
                       min: {{minvalue}},
                       max: {{maxvalue}},
                       stop: function(event, ui) {
                       var list_value = $("#{{slider_id}}").slider("value");
                       $(".{{klass}}").hide();
                       $("#{{klass}}-"+list_value).show();}
                       })</script>
""")


def build_html_slider(slices_range, slides_klass, slider_id):
    """ Build an html slider for a given slices range and a slices klass """
    return slider_template.substitute(slider_id=slider_id,
                                      klass=slides_klass,
                                      minvalue=slices_range[0],
                                      maxvalue=slices_range[-1])

###############################################################################
# HTML scan renderer

header_template = Template(u"""
<!DOCTYPE html>
<html lang="fr">
<head>
{{include}}
<script type="text/javascript">

        function togglebutton(class_name){
            $(class_name).toggle();

            if ($(class_name + '-btn').hasClass('active'))
                $(class_name + '-btn').removeClass('active');
            else
                $(class_name + '-btn').addClass('active');
        }
        </script>
<style type="text/css">

body {
    line-height: 1.5em;
    font-family: arial, sans-serif;
}

h1 {
    font-size: 30px;
    text-align: center;
}

h4 {
    text-align: center;
}

a, a:hover{
    color: #333333;
}

li{
    list-style-type:none;
}

#wrapper {
    text-align: left;
    margin: 5em auto;
    width: 700px;
}

#container{
    position: relative;
}

#toc {
  background: #a8a599;
  position: fixed;
  width: 20%;
  height: 100%;
  margin-top: 45px;
  overflow: auto;
}

#toc li {
    overflow: hidden;
    padding-bottom: 2px;
    margin-left: 20px;
}

#toc a {
    padding: 0 0 3px 2px;
}

#toc span {
    float: left;
    padding: 0 2px 3px 0;
}

div.footer {
    background-color: #C0C0C0;
    color: #000000;
    padding: 3px 8px 3px 0;
    clear: both;
    font-size: 0.8em;
    text-align: right;
}

</style>
</head>
<body>

<nav class="navbar navbar-inverse navbar-fixed-top" role="navigation">

<div class="container">

<h3 class="navbar-text" style="color:white">{{title}}</h3>

<ul class="nav nav-pills navbar-right" style="margin-top: 7px;">

    <li class="active raw-btn">
        <a href="#" onclick="togglebutton('.raw')">Raw</a>
    </li>
    <li class="active evoked-btn">
        <a href="#"  onclick="togglebutton('.evoked')">Ave</a>
    </li>
    <li class="active forward-btn">
        <a href="#" onclick="togglebutton('.forward')">Forward</a>
    </li>
    <li class="active covariance-btn">
        <a href="#" onclick="togglebutton('.covariance')">Cov</a>
    </li>
    <li class="active events-btn">
        <a href="#" onclick="togglebutton('.events')">Eve</a>
    </li>
    <li class="active trans-btn">
        <a href="#" onclick="togglebutton('.trans')">Trans</a>
    </li>
    <li class="active slices-images-btn">
        <a href="#" onclick="togglebutton('.slices-images')">Slices</a>
    </li>
</ul>

</div>

</nav>
""")

footer_template = HTMLTemplate(u"""
</div></body>
<div class="footer">
        &copy; Copyright 2012-2013, MNE Developers.
      Created on {{date}}.
      Powered by <a href="http://martinos.org/mne">MNE.
</div>
</html>
""")

image_template = HTMLTemplate(u"""
<li class="{{div_klass}}" id="{{id}}" {{if not show}}style="display: none"
{{endif}}>
{{if caption}}
<h4>{{caption}}</h4>
{{endif}}
<div class="thumbnail">
<img alt="" style="width:50%;" src="data:image/png;base64,{{img}}">
</div>
</li>
""")

repr_template = Template(u"""
<li class="{{div_klass}}" id="{{id}}">
<h4>{{caption}}</h4><hr>
{{repr}}
<hr></li>
""")


class Report(object):
    """Object for rendering HTML"""

    def __init__(self, info_fname, subjects_dir=None, subject=None,
                 title=None, dpi=1):
        """
        info_fname : str
            Name of the file containing the info dictionary
        subjects_dir : str | None
            Path to the SUBJECTS_DIR. If None, the path is obtained by using
            the environment variable SUBJECTS_DIR.
        subject : str | None
            Subject name.
        title : str
            Title of the report.
        """
        self.info_fname = info_fname
        self.subjects_dir = subjects_dir
        self.subject = subject
        self.title = title
        self.dpi = dpi

        self.initial_id = 0
        self.html = []
        self.fnames = []  # List of file names rendered

        self.init_render()  # Initialize the renderer

    def get_id(self):
        self.initial_id += 1
        return self.initial_id

    def add_section(self, figs, captions):
        """Append custom user-defined figures.

        Parameters
        ----------
        figs : list of matplotlib.pyplot.Figure
            A list of figures to be included in the report.
        captions : list of str
            A list of captions to the figures.
        """
        html = []
        for fig, caption in zip(figs, captions):
            global_id = self.get_id()
            div_klass = 'custom'
            img_klass = 'custom'
            img = _fig_to_img(fig)
            html.append(image_template.substitute(img=img, id=global_id,
                                                  div_klass=div_klass,
                                                  img_klass=img_klass,
                                                  caption=caption,
                                                  show=True))
            self.fnames.append(img_klass)
        self.html.append(''.join(html))

    ###########################################################################
    # HTML rendering
    def render_one_axe(self, slices_iter, name, global_id=None, cmap='gray'):
        """ Render one axe of the array """
        global_id = global_id or name
        html = []
        slices, slices_range = [], []
        first = True
        html.append(u'<div class="col-xs-6 col-md-4">')
        slides_klass = '%s-%s' % (name, global_id)
        img_klass = 'slideimg-%s' % name
        for ind, data in slices_iter:
            slices_range.append(ind)
            caption = u'Slice %s %s' % (name, ind)
            slice_id = '%s-%s-%s' % (name, global_id, ind)
            div_klass = 'span12 %s' % slides_klass
            img = _build_image(data, dpi=self.dpi, cmap=cmap)
            slices.append(build_html_image(img, slice_id, div_klass, img_klass,
                                           caption, first))
            first = False
        # Render the slider
        slider_id = 'select-%s-%s' % (name, global_id)
        html.append(build_html_slider(slices_range, slides_klass, slider_id))
        html.append(u'<ul class="thumbnails">')
        # Render the slices
        html.append(u'\n'.join(slices))
        html.append(u'</ul>')
        html.append(u'</div>')
        return '\n'.join(html)

    ###########################################################################
    # global rendering functions
    def init_render(self):
        """ Initialize the renderer
        """
        inc_fnames = ['bootstrap.min.js', 'jquery-1.10.2.min.js',
                      'jquery-ui.js', 'bootstrap.min.css', 'jquery-ui.css']

        include = list()
        for inc_fname in inc_fnames:
            print('Embedding : %s' % inc_fname)
            f = open(op.join(op.dirname(__file__), 'html', inc_fname),
                     'r')
            if inc_fname.endswith('.js'):
                include.append(u'<script type="text/javascript">'
                               + f.read() + u'</script>')
            elif inc_fname.endswith('.css'):
                include.append(u'<style type="text/css">'
                               + f.read() + u'</style>')
            f.close()

        html = header_template.substitute(title=self.title,
                                          include=''.join(include))
        self.html.append(html)

    def render_folder(self, data_path):
        """Renders all the files in the folder.

        Parameters
        ----------
        data_path : str
            Path to the folder containing data whose HTML report will be
            created.
        """
        self.data_path = data_path

        if self.title is None:
            self.title = 'MNE Report for ...%s' % self.data_path[-20:]

        folders = []

        fnames = _recursive_search(self.data_path, '*.fif')
        fnames += glob(op.join(self.subjects_dir, self.subject,
                       'mri', 'T1.mgz'))

        info = read_info(self.info_fname)

        for fname in fnames:
            print "Rendering : %s" % op.join('...' + self.data_path[-20:],
                                             fname)
            try:
                if fname.endswith(('.nii', '.nii.gz', '.mgh', '.mgz')):
                    cmap = 'gray'
                    if 'aseg' in fname:
                        cmap = 'spectral'
                    self.render_image(fname, surfaces=True, cmap=cmap)
                    self.fnames.append(fname)
                    pass
                elif fname.endswith(('raw.fif', 'sss.fif')):
                    self.render_raw(fname)
                    self.fnames.append(fname)
                elif fname.endswith(('-fwd.fif', '-fwd.fif.gz')):
                    self.render_forward(fname)
                    self.fnames.append(fname)
                elif fname.endswith(('-ave.fif')):
                    self.render_evoked(fname)
                    self.fnames.append(fname)
                elif fname.endswith(('-eve.fif')):
                    self.render_eve(fname, info)
                    self.fnames.append(fname)
                elif fname.endswith(('-cov.fif')):
                    self.render_cov(fname)
                    self.fnames.append(fname)
                elif fname.endswith(('-trans.fif')):
                    self.render_trans(fname, self.data_path, info,
                                      self.subject, self.subjects_dir)
                    self.fnames.append(fname)
                elif op.isdir(fname):
                    folders.append(fname)
                    print folders
            except Exception, e:
                print e

        self.render_bem(subject=self.subject,
                        subjects_dir=self.subjects_dir,
                        orientation='coronal')
        self.fnames.append('bem')

    def save(self, fname='report.html'):
        """
        Parameters
        ----------
        fname : str
            File name of the report.
        """

        print('Rendering : Table of Contents')
        self.render_toc()

        html = footer_template.substitute(date=time.strftime("%B %d, %Y"))
        self.html.append(html)

        fname = op.join(self.data_path, fname)
        fobj = open(fname, 'w')
        fobj.write(''.join(self.html))
        fobj.close()

        webbrowser.open_new_tab(fname)

        return fname

    def render_toc(self):
        html = u'<div id="container">'
        html += u'<div id="toc"><h1>Table of Contents</h1>'

        global_id = 1
        for fname in self.fnames:

            print('\t... %s' % fname[-20:])

            # identify bad file naming patterns and highlight them
            if not fname.endswith(('-eve.fif', '-ave.fif', '-cov.fif',
                                   '-sol.fif', '-fwd.fif', '-inv.fif',
                                   '-src.fif', '-trans.fif', 'raw.fif',
                                   'T1.mgz')):
                color = 'red'
            else:
                color = ''

            # assign class names to allow toggling with buttons
            if fname.endswith(('-eve.fif')):
                class_name = 'events'
            elif fname.endswith(('-ave.fif')):
                class_name = 'evoked'
            elif fname.endswith(('-cov.fif')):
                class_name = 'covariance'
            elif fname.endswith(('raw.fif', 'sss.fif')):
                class_name = 'raw'
            elif fname.endswith(('-trans.fif')):
                class_name = 'trans'
            elif fname.endswith(('-fwd.fif')):
                class_name = 'forward'
            elif fname.endswith(('.nii', '.nii.gz', '.mgh', '.mgz')):
                class_name = 'slices-images'

            if fname.endswith(('.nii', '.nii.gz', '.mgh', '.mgz', 'raw.fif',
                               'sss.fif', '-eve.fif', '-cov.fif',
                               '-trans.fif', '-fwd.fif')):
                html += (u'\n\t<li class="%s"><a href="#%d"><span title="%s" '
                         'style="color:%s"> %s </span>'
                         '</a></li>' % (class_name, global_id, fname,
                                        color, os.path.basename(fname)))
                global_id += 1

            # loop through conditions for evoked
            elif fname.endswith(('-ave.fif')):
                # XXX: remove redundant read_evokeds
                evokeds = read_evokeds(fname, baseline=(None, 0),
                                       verbose=False)

                html += (u'\n\t<li class="evoked"><span title="%s" '
                         'style="color:%s"> %s </span>'
                         % (fname, color, os.path.basename(fname)))

                html += u'<li class="evoked"><ul>'
                for ev in evokeds:
                    html += (u'\n\t<li class="evoked"><a href="#%d">'
                             '<span title="%s" style="color:%s"> %s'
                             '</span></a></li>'
                             % (global_id, fname, color, ev.comment))
                    global_id += 1
                html += u'</ul></li>'

            elif fname == 'bem':
                html += (u'\n\t<li><a href="#%d"><span> %s</span></a></li>' %
                         (global_id, 'BEM contours'))
                global_id += 1

            else:
                html += (u'\n\t<li><a href="#%d"><span> %s</span></a></li>' %
                         (global_id, 'custom'))
                global_id += 1

        html += u'\n</ul></div>'

        html += u'<div style="margin-left: 22%;">'

        self.html.insert(1, html)  # insert TOC just after header

    def render_array(self, array, global_id=None, surfaces=True, cmap='gray',
                     limits=None):
        html = []
        html.append(u'<div class="row">')
        # Axial
        limits = limits or {}
        axial_limit = limits.get('axial')
        axial_slices_gen = iterate_axial_slices(array, axial_limit)
        html.append(
            self.render_one_axe(axial_slices_gen, 'axial', global_id, cmap))
        # Sagittal
        sagittal_limit = limits.get('sagittal')
        sagittal_slices_gen = iterate_sagittal_slices(array, sagittal_limit)
        html.append(self.render_one_axe(sagittal_slices_gen, 'sagittal',
                    global_id, cmap))
        html.append(u'</div>')
        html.append(u'<div class="row">')
        # Coronal
        coronal_limit = limits.get('coronal')
        coronal_slices_gen = iterate_coronal_slices(array, coronal_limit)
        html.append(
            self.render_one_axe(coronal_slices_gen, 'coronal',
                                global_id, cmap))
        # Close section
        html.append(u'</div>')
        return '\n'.join(html)

    def render_one_bem_axe(self, mri_fname, surf_fnames, global_id,
                           shape, orientation='coronal'):

        orientation_name2axis = dict(sagittal=0, axial=1, coronal=2)
        orientation_axis = orientation_name2axis[orientation]
        n_slices = shape[orientation_axis]
        orig_size = np.roll(shape, orientation_axis)[[1, 2]]

        name = orientation
        html, img = [], []
        slices, slices_range = [], []
        first = True
        html.append(u'<div class="col-xs-6 col-md-4">')
        slides_klass = '%s-%s' % (name, global_id)
        img_klass = 'slideimg-%s' % name
        for sl in range(n_slices // 3, n_slices // 2):
            print('Rendering BEM contours : orientation = %s, '
                  'slice = %d' % (orientation, sl))
            slices_range.append(sl)
            caption = u'Slice %s %s' % (name, sl)
            slice_id = '%s-%s-%s' % (name, global_id, sl)
            div_klass = 'span12 %s' % slides_klass

            fig = _plot_mri_contours(mri_fname, surf_fnames,
                                     orientation=orientation,
                                     slices=[sl], show=False)
            img = fig2im('test', fig, orig_size)
            slices.append(build_html_image(img, slice_id, div_klass, img_klass,
                                           caption, first))
            first = False

        # Render the slider
        slider_id = 'select-%s-%s' % (name, global_id)
        html.append(build_html_slider(slices_range, slides_klass, slider_id))
        html.append(u'<ul class="thumbnails">')
        # Render the slices
        html.append(u'\n'.join(slices))
        html.append(u'</ul>')
        html.append(u'</div>')

        return '\n'.join(html)

    def render_image(self, image, surfaces=True, cmap='gray'):

        import nibabel as nib

        global_id = self.get_id()

        nim = nib.load(image)
        data = nim.get_data()
        shape = data.shape
        limits = {'sagittal': range(shape[0] // 3, shape[0] // 2),
                  'axial': range(shape[1] // 3, shape[1] // 2),
                  'coronal': range(shape[2] // 3, shape[2] // 2)}
        name = op.basename(image)
        html = u'<li class="slices-images" id="%d">\n' % global_id
        html += u'<h2>%s</h2>\n' % name
        html += self.render_array(data, global_id=global_id,
                                  surfaces=True, cmap=cmap, limits=limits)
        html += u'</li>\n'
        self.html.append(html)

    def render_raw(self, raw_fname):
        global_id = self.get_id()
        div_klass = 'raw'
        caption = u'Raw : %s' % raw_fname

        raw = Raw(raw_fname)

        repr_raw = re.sub('>', '', re.sub('<', '', repr(raw)))
        repr_info = re.sub('\\n', '\\n</br>',
                           re.sub('>', '',
                                  re.sub('<', '',
                                         repr(raw.info))))

        repr_html = repr_raw + '%s<br/>%s' % (repr_raw, repr_info)

        html = repr_template.substitute(div_klass=div_klass,
                                        id=global_id,
                                        caption=caption,
                                        repr=repr_html)
        self.html.append(html)

    def render_forward(self, fwd_fname):
        global_id = self.get_id()
        div_klass = 'forward'
        caption = u'Forward: %s' % fwd_fname

        fwd = read_forward_solution(fwd_fname)

        repr_fwd = re.sub('>', '', re.sub('<', '', repr(fwd)))

        html = repr_template.substitute(div_klass=div_klass,
                                        id=global_id,
                                        caption=caption,
                                        repr=repr_fwd)

        self.html.append(html)

    def render_evoked(self, evoked_fname, figsize=None):
        evokeds = read_evokeds(evoked_fname, baseline=(None, 0),
                               verbose=False)

        html = []
        for ev in evokeds:
            global_id = self.get_id()
            img = _fig_to_img(ev.plot(show=False))
            caption = 'Evoked : ' + evoked_fname + ' (' + ev.comment + ')'
            div_klass = 'evoked'
            img_klass = 'evoked'
            show = True
            html.append(image_template.substitute(img=img, id=global_id,
                                                  div_klass=div_klass,
                                                  img_klass=img_klass,
                                                  caption=caption,
                                                  show=show))

        self.html.append('\n'.join(html))

    def render_eve(self, eve_fname, info):

        import matplotlib.pyplot as plt

        global_id = self.get_id()
        events = read_events(eve_fname)
        sfreq = info['sfreq']
        plt.close("all")  # close figures to avoid weird plot
        ax = plot_events(events, sfreq=sfreq, show=False)
        img = _fig_to_img(ax.gcf())
        caption = 'Events : ' + eve_fname
        div_klass = 'events'
        img_klass = 'events'
        show = True
        html = image_template.substitute(img=img, id=global_id,
                                         div_klass=div_klass,
                                         img_klass=img_klass,
                                         caption=caption,
                                         show=show)
        self.html.append(html)

    def render_cov(self, cov_fname):

        import matplotlib.pyplot as plt

        global_id = self.get_id()
        cov = Covariance(cov_fname)
        plt.matshow(cov.data)

        img = _fig_to_img(plt.gcf())
        caption = 'Covariance : ' + cov_fname
        div_klass = 'covariance'
        img_klass = 'covariance'
        show = True
        html = image_template.substitute(img=img, id=global_id,
                                         div_klass=div_klass,
                                         img_klass=img_klass,
                                         caption=caption,
                                         show=show)
        self.html.append(html)

    def render_trans(self, trans_fname, path, info, subject,
                     subjects_dir):
        from PIL import Image
        import mayavi

        fig = plot_trans(info, trans_fname=trans_fname,
                         subject=subject, subjects_dir=subjects_dir)

        if isinstance(fig, mayavi.core.scene.Scene):
            global_id = self.get_id()

            # XXX: save_bmp / save_png / ...
            fig.scene.save_bmp(tempdir + 'test')
            output = StringIO.StringIO()
            Image.open(tempdir + 'test').save(output, format='bmp')
            img = output.getvalue().encode('base64')

            caption = 'Trans : ' + trans_fname
            div_klass = 'trans'
            img_klass = 'trans'
            show = True
            html = image_template.substitute(img=img, id=global_id,
                                             div_klass=div_klass,
                                             img_klass=img_klass,
                                             caption=caption,
                                             show=show)
            self.html.append(html)

    def render_bem(self, subject, subjects_dir, orientation='coronal'):

        import nibabel as nib

        global_id = self.get_id()
        name, caption = 'BEM', 'BEM contours'

        # Get the MRI filename
        mri_fname = op.join(subjects_dir, subject, 'mri', 'T1.mgz')
        if not op.isfile(mri_fname):
            raise IOError('MRI file "%s" does not exist' % mri_fname)

        # Get the BEM surface filenames
        bem_path = op.join(subjects_dir, subject, 'bem')

        if not op.isdir(bem_path):
            raise IOError('Subject bem directory "%s" does not exist' %
                          bem_path)

        surf_fnames = []
        for surf_name in ['*inner_skull', '*outer_skull', '*outer_skin']:
            surf_fname = glob(op.join(bem_path, surf_name + '.surf'))
            if len(surf_name) > 0:
                surf_fname = surf_fname[0]
            else:
                raise IOError('No surface found for %s.' % surf_name)
            if not op.isfile(surf_fname):
                raise IOError('Surface file "%s" does not exist' % surf_fname)
            surf_fnames.append(surf_fname)

        # XXX : find a better way to get max range of slices
        nim = nib.load(mri_fname)
        data = nim.get_data()

        html = []
        html += u'<h2>%s</h2>\n' % name
        html += u'<li class="bem-slices" id="%d">\n' % global_id
        html += u'<div class="row">'
        html += self.render_one_bem_axe(mri_fname, surf_fnames, global_id,
                                        data.shape, orientation='sagittal')
        html += self.render_one_bem_axe(mri_fname, surf_fnames, global_id,
                                        data.shape, orientation='axial')
        html += u'</div><div class="row">'
        html += self.render_one_bem_axe(mri_fname, surf_fnames, global_id,
                                        data.shape, orientation='coronal')
        html += u'</div>'
        html += u'</li>\n'
        self.html.append(''.join(html))


def fig2im(fname, fig, orig_size):
    import matplotlib.pyplot as plt
    from PIL import Image

    fig_size = fig.get_size_inches()
    w, h = orig_size[0], orig_size[1]
    w2, h2 = fig_size[0], fig_size[1]
    fig.set_size_inches([(w2 / w) * w, (w2 / w) * h])
    a = fig.gca()
    a.set_xticks([]), a.set_yticks([])
    plt.xlim(0, h), plt.ylim(w, 0)
    fig.savefig(tempdir + fname, bbox_inches='tight',
                pad_inches=0, format='png')
    Image.open(tempdir + fname).resize((w, h)).save(fname, format='png')
    output = StringIO.StringIO()
    Image.open(tempdir + fname).save(output, format='png')
    return output.getvalue().encode('base64')


def _fig_to_img(fig):
    """Auxiliary function for fig <-> binary image.
    """
    output = StringIO.StringIO()
    fig.savefig(output, format='png')

    return output.getvalue().encode('base64')


def _recursive_search(path, pattern):
    """Auxiliary function for recursive_search of the directory.
    """
    filtered_files = list()
    for dirpath, dirnames, files in os.walk(path):
        for f in fnmatch.filter(files, pattern):
            filtered_files.append(op.join(dirpath, f))

    return filtered_files