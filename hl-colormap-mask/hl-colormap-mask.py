#!/usr/bin/env python2

from gimpfu import *
from array import array


AUTHOR           = 'Psycrow'
COPYRIGHT        = AUTHOR
COPYRIGHT_YEAR   = '2020'

LOAD_PROC        = 'hl-colormap-mask'

class ColorMapMask:
    __slots__ = [
        'max_topcolors_num',
        'max_bottomcolors_num',
        'dither_type'
    ]

    def __init__(self, max_topcolors_num, max_bottomcolors_num, dither_type):
        self.max_topcolors_num = max_topcolors_num
        self.max_bottomcolors_num = max_bottomcolors_num
        self.dither_type = dither_type

    def _calculate_color_mask(self, image_width, image_height, colors_num, colors_raw, layer_mask, mask_index):
        if not colors_num:
            return [], None

        image = gimp.Image(image_width, image_height, RGB_IMAGE)
        layer = gimp.Layer(image, "temp", image_width, image_height, RGB, 100, NORMAL_MODE)

        rgn = layer.get_pixel_rgn(0, 0, image_width, image_height)
        rgn_raw = ''
        for i in xrange(image_width * image_height):
            if layer_mask[i] == mask_index:
                rgn_raw += colors_raw[i*3:i*3+3]
            else:
                rgn_raw += '\0\0\0'
        rgn[:, :] = rgn_raw

        layer.flush()
        pdb.gimp_image_insert_layer(image, layer, None, 0)
        pdb.gimp_image_convert_indexed(image, self.dither_type, MAKE_PALETTE, colors_num, 0, 0, '')

        _, colormap = pdb.gimp_image_get_colormap(image)
        rgn = image.layers[0].get_pixel_rgn(0, 0, image_width, image_height)
        indices = array('B', rgn[:, :])
        gimp.delete(image)

        return list(colormap), indices

    def process(self, image):
        # Gimp does not support indexed mode if the image contains layer groups, so delete them
        for layer in image.layers:
            if pdb.gimp_item_is_group(layer):
                pdb.gimp_image_merge_layer_group(image, layer)

        # Get layers
        layers_num = len(image.layers)
        if layers_num == 3:
            mask_top_layer, mask_bottom_layer = image.layers[0:2]
        elif layers_num == 2:
            mask_top_layer, mask_bottom_layer = image.layers[0], None
        else:
            return
        base_layer = image.layers[-1]

        # Remove alpha from base layer
        pdb.gimp_layer_flatten(base_layer)

        # Resize layers to image size
        pdb.gimp_layer_resize_to_image_size(base_layer)
        pdb.gimp_layer_resize_to_image_size(mask_top_layer)
        if mask_bottom_layer:
            pdb.gimp_layer_resize_to_image_size(mask_bottom_layer)

        image_width = base_layer.width
        image_height = base_layer.height

        # Get colors and masks
        colors_raw = base_layer.get_pixel_rgn(0, 0, image_width, image_height)[:, :]
        top_mask_raw = array('B', mask_top_layer.get_pixel_rgn(0, 0, image_width, image_height)[:, :])
        if mask_bottom_layer:
            bottom_mask_raw = array('B', mask_bottom_layer.get_pixel_rgn(0, 0, image_width, image_height)[:, :])

        top_colors_set, bottom_colors_set, base_colors_set = set(), set(), set()
        layer_mask = []

        for i in xrange(image_width * image_height):
            color = colors_raw[i*3:i*3+3]
            if top_mask_raw[i * 4 + 3] > 0:
                top_colors_set.add(color)
                layer_mask.append(2)
            elif mask_bottom_layer and bottom_mask_raw[i * 4 + 3] > 0:
                bottom_colors_set.add(color)
                layer_mask.append(1)
            else:
                base_colors_set.add(color)
                layer_mask.append(0)

        # Delete mask layers
        image.remove_layer(mask_top_layer)
        if mask_bottom_layer:
            image.remove_layer(mask_bottom_layer)

        # Get color numbers
        top_colors_num = len(top_colors_set)
        bottom_colors_num = len(bottom_colors_set)
        base_colors_num = len(base_colors_set)

        if not top_colors_num:
            return

        if top_colors_num + base_colors_num + bottom_colors_num > 256:
            top_colors_num = min(int(self.max_topcolors_num), top_colors_num)
            bottom_colors_num = min(int(self.max_bottomcolors_num), bottom_colors_num)
        base_colors_num = 256 - (top_colors_num + bottom_colors_num)

        # Calculate color masks
        top_colors, top_indices = self._calculate_color_mask(image_width, image_height, top_colors_num, colors_raw, layer_mask, 2)
        bottom_colors, bottom_indices = self._calculate_color_mask(image_width, image_height, bottom_colors_num, colors_raw, layer_mask, 1)
        base_colors, base_indices = self._calculate_color_mask(image_width, image_height, base_colors_num, colors_raw, layer_mask, 0)
        all_colors = top_colors + bottom_colors + base_colors

        # Convert indexed and set colormap
        pdb.gimp_image_convert_indexed(image, self.dither_type, MAKE_PALETTE, 256, 0, 0, '')
        pdb.gimp_image_set_colormap(image, len(all_colors), all_colors)

        # Rename layer and set colors
        layer = image.layers[0]

        topcolor_offset = top_colors_num - 1
        if bottom_colors_num:
            bottomcolor_offset = top_colors_num + bottom_colors_num - 1
        else:
            bottomcolor_offset = 0
        pdb.gimp_item_set_name(layer, "Remap1_000_%03d_%03d" % (topcolor_offset, bottomcolor_offset))

        rgn = layer.get_pixel_rgn(0, 0, image_width, image_height)
        indices = array('B', rgn[:, :])
        for i in xrange(len(indices)):
            if layer_mask[i] == 2:
                indices[i] = top_indices[i]
            elif layer_mask[i] == 1 and bottom_colors_num:
                indices[i] = bottom_indices[i] + top_colors_num
            else:
                indices[i] = base_indices[i] + top_colors_num + bottom_colors_num
        rgn[:, :] = indices.tostring()
        layer.flush()


def hl_colormap_mask(image, drawable, max_topcolors_num, max_bottomcolors_num, dither_type):
    pdb.gimp_context_push()
    pdb.gimp_image_undo_group_start(image)

    ColorMapMask(max_topcolors_num, max_bottomcolors_num, dither_type).process(image)

    pdb.gimp_displays_flush()

    pdb.gimp_image_undo_group_end(image)
    pdb.gimp_context_pop()


register(
    LOAD_PROC,
    'Converts an image by grouping the palette to create topcolor and bottomcolor sections from layer masks for Half-Life game',
    '',
    AUTHOR,
    COPYRIGHT,
    COPYRIGHT_YEAR,
    'Topcolor and bottomcolor from layers',
    'RGBA',
    [
        (PF_IMAGE, 'image', 'Input image', None),
        (PF_DRAWABLE, 'drawable', 'Input drawable', None),
        (PF_SLIDER, 'max_topcolors_num', 'Maximum top colors number {1 - 256}', 128, (1, 256, 1)),
        (PF_SLIDER, 'max_bottomcolors_num', 'Maximum bottom colors number {0 - 256}', 0, (0, 256, 1)),
        (PF_OPTION, 'dither-type', 'The dither type to use', 0, (
            'None',
            'FS (normal)',
            'FS (reduced color bleeding)',
            'Positioned'
        )),
    ],
    [],
    hl_colormap_mask, menu='<Image>/Image/Half-Life/'
)

main()
