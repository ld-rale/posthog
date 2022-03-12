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

################################################################################
# HIGHLIGHT - Mixins let a class adopt methods and attributes of another class. 
# - In this case, other classes may adopt properties or methods from the StructuredViewSetMixin class.

# Mixins are used if you don't want a class to inherit from another class (i.e. be its child class) but you want it to adopt some attributes / methods. 
# - You can think of mixins as uncles and aunts but not necessarily parents. 
# - avoid issues and complexities of multiple inheritance 
# - - (i.e. if class D has parents B and C, both of whose parent is A, then does D use B or C's version of any given method)

# Tutorial Example: https://www.patterns.dev/posts/mixin-pattern/

# Mixins are used for: 
# - (A) reuse 
# - - (i.e. avoiding code repetition and promoting code reuse, so there is less complexity and room for error)
# - - helps with collaboration
# - - in https://www.patterns.dev/posts/mixin-pattern/, all animals (dogs, cats, etc) can use the animalFunctionality mixin

# - (B) providing optional methods / properties 
# - - (i.e. you want a class to avail of several optional properties or methods)
# - - in https://stackoverflow.com/a/547714/1194050, mixins let you allow more supports as needed, but not by default, to instances of Request 

# - (C) compartmentalization
# - - (i.e. code at different levels [data touching, logic, view touching, etc] should be separated so different developers can collaborate easily)
# - - in https://www.patterns.dev/posts/mixin-pattern/, functionality for animals in general in animalFunctionality can be separated from dog-specific functionality

# ACTIVITY 1 - Scan the mixin code below and summarize what you think the Mixin does.

# ACTIVITY 2 - Highlight at least 5 classes in this codebase that use this mixin. 
# - Hint: use VS Code's search feature.

#(note to experimenter: show highlight / mixin label on file in filesystem during demo)
################################################################################
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

    ############################################################################
    # HIGHLIGHT - Instances of some classes (see Insight.py line 173) have used this Mixin method.

    # ACTIVITY 3A - Highlight where this Mixin's methods get_queryset is being adopted / used by a class (or class instance) that includes this Mixin. 
    # - Hint: look at the other highlighted files in the file system.
    # - Trigger the mixin code (i.e. the "mixed in" code) below by using the software application, writing print statements, and watching them trigger.
    # - - You can uncomment the prints we included and print variables too.
    # - Describe how this Mixin's get_queryset method is being used there.

    # [SKIP] ACTIVITY 5 - Now we are going remove all declarations of StructuredViewSetMixin and also the AnalyticsDestroyModelMixin.
    # [SKIP] - And you should fill in each blank, based on the methods / properties that the class adopting the mixins uses.
    # [SKIP] (note to self: show how the code snippets would get removed and one would have to fill them back in)  
    ############################################################################
    def get_queryset(self):
        print("GOBI in get_queryset")
        queryset = super().get_queryset()
        return self.filter_queryset_by_parents_lookups(queryset)

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

    ############################################################################
    # HIGHLIGHT - Instances of some classes (see Insight.py line 205) have used this Mixin property.

    # ACTIVITY 3B - Highlight where this Mixin's property team is being adopted / used by a class (or class instance) that includes this Mixin. 
    # - Hint: look at the other highlighted files in the file system.
    # - Trigger the mixin code (i.e. the "mixed in" code) below by using the software application, writing print statements, and watching them trigger.
    # - Describe how this Mixin's team property is being used there.

    ############################################################################
    @property
    def team(self) -> Team:
        print("GOBI in team")
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
        parents_query_dict = self.parents_query_dict.copy()

        for source, destination in self.filter_rewrite_rules.items():
            parents_query_dict[destination] = parents_query_dict[source]
            del parents_query_dict[source]
        if parents_query_dict:
            try:
                return queryset.filter(**parents_query_dict)
            except ValueError:
                raise NotFound()
        else:
            return queryset

    @cached_property
    def parents_query_dict(self) -> Dict[str, Any]:
        # used to override the last visited project if there's a token in the request
        team_from_request = self._get_team_from_request()

        if self.legacy_team_compatibility:
            if not self.request.user.is_authenticated:
                raise AuthenticationFailed()
            project = team_from_request or self.request.user.team
            if project is None:
                raise ValidationError("This endpoint requires a project.")
            return {"team_id": project.id}
        result = {}
        # process URL paremetrs (here called kwargs), such as organization_id in /api/organizations/:organization_id/
        for kwarg_name, kwarg_value in self.kwargs.items():
            # drf-extensions nested parameters are prefixed
            if kwarg_name.startswith(extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX):
                query_lookup = kwarg_name.replace(
                    extensions_api_settings.DEFAULT_PARENT_LOOKUP_KWARG_NAME_PREFIX, "", 1
                )
                query_value = kwarg_value
                if query_value == "@current":
                    if not self.request.user.is_authenticated:
                        raise AuthenticationFailed()
                    if query_lookup == "team_id":
                        project = self.request.user.team
                        if project is None:
                            raise NotFound("Project not found.")
                        query_value = project.id
                    elif query_lookup == "organization_id":
                        organization = self.request.user.organization
                        if organization is None:
                            raise NotFound("Organization not found.")
                        query_value = organization.id
                elif query_lookup == "team_id":
                    try:
                        query_value = team_from_request.id if team_from_request else int(query_value)
                    except ValueError:
                        raise NotFound()
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
