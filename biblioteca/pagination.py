from django.core.paginator import InvalidPage
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param


class BibliotecaPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        page_size = self.get_page_size(request)
        if not page_size:
            return None

        paginator = self.django_paginator_class(queryset, page_size)
        page_number = self.get_page_number(request, paginator)

        try:
            self.page = paginator.page(page_number)
            self.out_of_range_page = None
        except InvalidPage as exc:
            try:
                requested_page = int(page_number)
            except (TypeError, ValueError):
                msg = self.invalid_page_message.format(
                    page_number=page_number,
                    message=str(exc),
                )
                raise NotFound(msg)

            if requested_page > paginator.num_pages:
                self.page = None
                self.paginator = paginator
                self.out_of_range_page = requested_page
                return []

            msg = self.invalid_page_message.format(
                page_number=page_number,
                message=str(exc),
            )
            raise NotFound(msg)

        return list(self.page)

    def _previous_link_for_empty_page(self):
        if not self.out_of_range_page or self.out_of_range_page <= 1:
            return None
        return replace_query_param(
            self.request.build_absolute_uri(),
            self.page_query_param,
            self.out_of_range_page - 1,
        )

    def get_paginated_response(self, data):
        if self.page is None:
            return Response({
                'count': self.paginator.count,
                'total_pages': self.paginator.num_pages,
                'page': self.out_of_range_page,
                'page_size': self.get_page_size(self.request),
                'next': None,
                'previous': self._previous_link_for_empty_page(),
                'results': data,
            })

        return Response({
            'count': self.page.paginator.count,
            'total_pages': self.page.paginator.num_pages,
            'page': self.page.number,
            'page_size': self.get_page_size(self.request),
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data,
        })
