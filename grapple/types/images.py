import graphene

from graphene_django import DjangoObjectType
from wagtail.images import get_image_model
from wagtail.images.models import Image as WagtailImage
from wagtail.images.models import Rendition as WagtailImageRendition
from wagtail.images.models import SourceImageIOError

from ..registry import registry
from ..settings import grapple_settings
from ..utils import get_media_item_url, resolve_queryset
from .collections import CollectionObjectType
from .structures import QuerySetList
from .tags import TagObjectType


def get_image_type():
    return registry.images.get(get_image_model(), ImageObjectType)


def get_rendition_type():
    rendition_mdl = get_image_model().renditions.rel.related_model
    return registry.images.get(rendition_mdl, ImageRenditionObjectType)


def rendition_allowed(rendition_filter):
    """Checks a given rendition filter is allowed"""
    allowed_filters = grapple_settings.ALLOWED_IMAGE_FILTERS
    if allowed_filters is None or not isinstance(allowed_filters, (list, tuple)):
        return True

    return rendition_filter in allowed_filters


class ImageRenditionObjectType(DjangoObjectType):
    id = graphene.ID(required=True)
    file = graphene.String(required=True)
    image = graphene.Field(lambda: get_image_type(), required=True)
    filter_spec = graphene.String(required=True)
    width = graphene.Int(required=True)
    height = graphene.Int(required=True)
    focal_point_key = graphene.String(required=True)
    focal_point = graphene.String()
    url = graphene.String(required=True)
    alt = graphene.String(required=True)
    background_position_style = graphene.String(required=True)

    class Meta:
        model = WagtailImageRendition

    def resolve_url(instance, info, **kwargs):
        return instance.full_url


class ImageObjectType(DjangoObjectType):
    id = graphene.ID(required=True)
    title = graphene.String(required=True)
    file = graphene.String(required=True)
    width = graphene.Int(required=True)
    height = graphene.Int(required=True)
    created_at = graphene.DateTime(required=True)
    focal_point_x = graphene.Int()
    focal_point_y = graphene.Int()
    focal_point_width = graphene.Int()
    focal_point_height = graphene.Int()
    file_size = graphene.Int()
    file_hash = graphene.String(required=True)
    src = graphene.String(required=True, deprecation_reason="Use the `url` attribute")
    url = graphene.String(required=True)
    aspect_ratio = graphene.Float(required=True)
    sizes = graphene.String(required=True)
    collection = graphene.Field(lambda: CollectionObjectType, required=True)
    tags = graphene.List(graphene.NonNull(lambda: TagObjectType), required=True)
    rendition = graphene.Field(
        lambda: get_rendition_type(),
        max=graphene.String(),
        min=graphene.String(),
        width=graphene.Int(),
        height=graphene.Int(),
        fill=graphene.String(),
        format=graphene.String(),
        bgcolor=graphene.String(),
        jpegquality=graphene.Int(),
        webpquality=graphene.Int(),
    )
    src_set = graphene.String(
        sizes=graphene.List(graphene.Int), format=graphene.String()
    )

    class Meta:
        model = WagtailImage

    def resolve_rendition(instance, info, **kwargs):
        """
        Render a custom rendition of the current image.
        """
        filters = "|".join([f"{key}-{val}" for key, val in kwargs.items()])

        # Only allowed the defined filters (thus renditions)
        if not rendition_allowed(filters):
            return
        try:
            return instance.get_rendition(filters)
        except SourceImageIOError:
            return

    def resolve_url(instance, info, **kwargs):
        """
        Get the uploaded image url.
        """
        return get_media_item_url(instance)

    def resolve_src(self, info, **kwargs):
        """
        Deprecated. Use the `url` attribute.
        """
        return get_media_item_url(self)

    def resolve_aspect_ratio(instance, info, **kwargs):
        """
        Calculate aspect ratio for the image.
        """
        return instance.width / instance.height

    def resolve_sizes(instance, info, **kwargs):
        return f"(max-width: {instance.width}px) 100vw, {instance.width}px"

    def resolve_tags(instance, info, **kwargs):
        return instance.tags.all()

    def resolve_src_set(instance, info, sizes, format=None, **kwargs):
        """
        Generate src set of renditions.
        """
        filter_suffix = f"|format-{format}" if format else ""
        format_kwarg = {"format": format} if format else {}
        if instance.file.name is not None:
            rendition_list = [
                ImageObjectType.resolve_rendition(
                    instance, info, width=width, **format_kwarg
                )
                for width in sizes
                if rendition_allowed(f"width-{width}{filter_suffix}")
            ]

            return ", ".join(
                [
                    f"{get_media_item_url(img)} {img.width}w"
                    for img in rendition_list
                    if img is not None
                ]
            )

        return ""


def ImagesQuery():
    mdl = get_image_model()
    mdl_type = get_image_type()

    class Mixin:
        image = graphene.Field(mdl_type, id=graphene.ID())
        images = QuerySetList(
            graphene.NonNull(mdl_type),
            enable_search=True,
            required=True,
            collection=graphene.Argument(
                graphene.ID, description="Filter by collection id"
            ),
        )
        image_type = graphene.String(required=True)

        def resolve_image(parent, info, id, **kwargs):
            """Returns an image given the id, if in a public collection"""
            try:
                return (
                    mdl.objects.filter(collection__view_restrictions__isnull=True)
                    .prefetch_renditions()
                    .get(pk=id)
                )
            except mdl.DoesNotExist:
                return None

        def resolve_images(parent, info, **kwargs):
            """Returns all images in a public collection"""
            return resolve_queryset(
                mdl.objects.filter(
                    collection__view_restrictions__isnull=True
                ).prefetch_renditions(),
                info,
                **kwargs,
            )

        # Give name of the image type, used to generate mixins
        def resolve_image_type(parent, info, **kwargs):
            return mdl_type

    return Mixin
