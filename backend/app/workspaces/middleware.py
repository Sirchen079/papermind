from starlette.responses import JSONResponse

from app.workspaces.context import bind_workspace


class WorkspaceMiddleware:
    """Hold immutable context until streaming and background work have finished.

    Pure ASGI avoids the context propagation limitations of BaseHTTPMiddleware.
    Existing /api URLs retain their explicit legacy-database meaning.
    """
    def __init__(self, app, registry):
        self.app, self.registry = app, registry

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope['path']
        context = self.registry.context('legacy')
        if path.startswith('/api/w/'):
            parts = path.split('/', 4)
            workspace_id = parts[3]
            try:
                context = self.registry.context(workspace_id)
            except LookupError as exc:
                return await JSONResponse({'detail': str(exc)}, status_code=404)(scope, receive, send)
            # Route on a copy, leaving the original request scope intact.
            scope = dict(scope)
            scope['path'] = '/api/' + (parts[4] if len(parts) == 5 else '')
            scope['raw_path'] = scope['path'].encode('utf-8')
        application_path = scope['path']
        global_route = (application_path in ('/api/health', '/api/workspaces')
                        or application_path.startswith('/api/workspaces/')
                        or application_path == '/api/shared-connections'
                        or application_path.startswith('/api/shared-connections/'))
        if application_path.startswith('/api/') and not global_route:
            reason = self.registry.unavailable_reason(context.id)
            if reason:
                return await JSONResponse({'detail': reason}, status_code=503)(scope, receive, send)
        with bind_workspace(context):
            await self.app(scope, receive, send)
