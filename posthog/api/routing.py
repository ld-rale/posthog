from functools import cached_property
from typing import TYPE_CHECKING, Any, Dict, Optional, cast

from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError
from rest_framework.viewsets import GenericViewSet
from rest_framework_extensions.routers import ExtendedDefaultRouter
from rest_framework_extensions.settings import extensions_api_settings

from posthog.api.utils import get_token
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

if TYPE_CHECKING:
    _GenericViewSet = GenericViewSet
else:
    _GenericViewSet = object


class DefaultRouterPlusPlus(ExtendedDefaultRouter):
    """DefaultRouter with optional trailing slash and drf-extensions nesting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trailing_slash = r"/?"

class StructuredViewSetMixin(_GenericViewSet):
    # This flag disables nested routing handling, reverting to the old request.user.team behavior
    # Allows for a smoother transition from the old flat API structure to the newer nested one
    legacy_team_compatibility: bool = False

    # Rewrite filter queries, so that for example foreign keys can be accessed
    # Example: {"team_id": "foo__team_id"} will make the viewset filtered by obj.foo.team_id instead of obj.team_id
    filter_rewrite_rules: Dict[str, str] = {}

    include_in_docs = True

    authentication_classes = [
        PersonalAPIKeyAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        print("\n\n===in SVSM get_queryset mixin method, data before:" + str(queryset) + "==\n\n")
        try:
            for i in queryset:
                print(str(i) + str(i.name) + " for team " + str(i.team))
        except:
            print("not the insight model, skipping")
        to_return = self.filter_queryset_by_parents_lookups(queryset)
        print("\n\n===in SVSM get_queryset mixin method, data after:" + str(to_return) + "==\n\n")
        try:
            for i in to_return:
                print(str(i) + str(i.name) + " for team " + str(i.team))
        except:
            print("not the insight model, skipping")
        return to_return

    @property
    def team_id(self) -> int:
        team_from_token = self._get_team_from_request()
        if team_from_token:
            return team_from_token.id

        if self.legacy_team_compatibility:
            user = cast(User, self.request.user)
            team = user.team
            assert team is not None
            return team.id
        return self.parents_query_dict["team_id"]

    @property
    def team(self) -> Team:
        team_from_token = self._get_team_from_request()
        if team_from_token:
            return team_from_token

        user = cast(User, self.request.user)
        if self.legacy_team_compatibility:
            team = user.team
            assert team is not None
            return team
        try:
            return Team.objects.get(id=self.team_id)
        except Team.DoesNotExist:
            raise NotFound(detail="Project not found.")

    @property
    def organization_id(self) -> str:
        try:
            return self.parents_query_dict["organization_id"]
        except KeyError:
            return str(self.team.organization_id)

    @property
    def organization(self) -> Organization:
        try:
            return Organization.objects.get(id=self.organization_id)
        except Organization.DoesNotExist:
            raise NotFound(detail="Organization not found.")

    def filter_queryset_by_parents_lookups(self, queryset):
        print("in filter_queryset_by_parents_lookups, queryset:" + str(queryset))
        parents_query_dict = self.parents_query_dict.copy()
        print("parents_query_dict", parents_query_dict)

        print("self.filter_rewrite_rules.items() " + str(self.filter_rewrite_rules.items()))
        for source, destination in self.filter_rewrite_rules.items():
            print("source: " + str(source) + " destination: " + str(destination))
            parents_query_dict[destination] = parents_query_dict[source]

            del parents_query_dict[source]
        if parents_query_dict:
            try:
                print("in try, parents_query_dict " + str(parents_query_dict))
                #print("in try, **parents_query_dict " + str(**parents_query_dict))
                return queryset.filter(**parents_query_dict)
            except ValueError:
                raise NotFound()
        else:
            return queryset

    @cached_property
    def parents_query_dict(self) -> Dict[str, Any]:
        # used to override the last visited project if there's a token in the request
        print("in parents_query_dict")
        team_from_request = self._get_team_from_request()
        print("in team_from_request " + str(team_from_request))

        print("self.legacy_team_compatibility:" + str(self.legacy_team_compatibility))
        if self.legacy_team_compatibility:
            print("self.request.user.is_authenticated", self.request.user.is_authenticated)
            if not self.request.user.is_authenticated:
                raise AuthenticationFailed()
            project = team_from_request or self.request.user.team
            print("project" + str(project))
            if project is None:
                print("project validation error")
                raise ValidationError("This endpoint requires a project.")
            print("about to return team_id, project.id")
            return {"team_id": project.id}
        result = {}
        # process URL paremetrs (here called kwargs), such as organization_id in /api/organizations/:organization_id/
        print("self.kwargs.items()" + str(self.kwargs.items()))
        for kwarg_name, kwarg_value in self.kwargs.items():
            print("kwarg_name " + str(kwarg_name) + " kwarg_value " + str(kwarg_value))
            # drf-extensions nested parameters are prefixed
            print("extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX " + str(extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX))
            if kwarg_name.startswith(extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX):
                query_lookup = kwarg_name.replace(
                    extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX, "", 1
                )
                print("query_lookup" + str(query_lookup))
                query_value = kwarg_value
                if query_value == "@current":
                    print("self.request.user.is_authenticated" + str(self.request.user.is_authenticated))
                    if not self.request.user.is_authenticated:
                        raise AuthenticationFailed()
                    if query_lookup == "team_id":
                        project = self.request.user.team
                        print("in team_id, project " + str(project))
                        if project is None:
                            raise NotFound("Project not found.")
                        query_value = project.id
                        print("query_value" + str(query_value))
                    elif query_lookup == "organization_id":
                        organization = self.request.user.organization
                        print("organization" + str(organization))
                        if organization is None:
                            raise NotFound("Organization not found.")
                        query_value = organization.id
                        print("query_value" + str(query_value))
                elif query_lookup == "team_id":
                    print("query_lookup" + str(query_lookup))
                    try:
                        query_value = team_from_request.id if team_from_request else int(query_value)
                        print("query_value" + str(query_value))
                    except ValueError:
                        raise NotFound()
                print("result, query_lookup, query_value" + str(result) + " " + str(query_lookup) + " " + str(query_value))
                result[query_lookup] = query_value
        return result

    def get_serializer_context(self) -> Dict[str, Any]:
        return {**super().get_serializer_context(), **self.parents_query_dict}

    def _get_team_from_request(self) -> Optional["Team"]:
        team_found = None
        token = get_token(None, self.request)

        if token:
            team = Team.objects.get_team_from_token(token)
            if team:
                team_found = team
            else:
                raise AuthenticationFailed()

        return team_found

    # Stdout tracing to see what legacy endpoints (non-project-nested) are still requested by the frontend
    # TODO: Delete below when no legacy endpoints are used anymore

    # def create(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.legacy_team_compatibility:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (create)")
    #     return super_cls.create(*args, **kwargs)

    # def retrieve(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.legacy_team_compatibility:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (retrieve)")
    #     return super_cls.retrieve(*args, **kwargs)

    # def list(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.legacy_team_compatibility:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (list)")
    #     return super_cls.list(*args, **kwargs)

    # def update(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.legacy_team_compatibility:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (update)")
    #     return super_cls.update(*args, **kwargs)

    # def delete(self, *args, **kwargs):
    #     super_cls = super()
    #     if self.legacy_team_compatibility:
    #         print(f"Legacy endpoint called – {super_cls.get_view_name()} (delete)")
    #     return super_cls.delete(*args, **kwargs)
