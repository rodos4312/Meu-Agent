"""Native owner project selection; remote pairing cannot choose arbitrary PC paths."""
import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from hermes_state_meu_projects import ProjectStore

router = APIRouter(prefix='/projects')


class Selection(BaseModel):
    directory: str = Field(max_length=4096)
    name: str = Field(min_length=1, max_length=180)
    session_id: str = Field(min_length=1, max_length=100)


@router.get('')
async def listing(request: Request):
    from hermes_cli.web_routers.mobile_preview import _scope
    _, authority = _scope(request)
    def read():
        store = ProjectStore(authority.db)
        result = store.catalog()
        with authority.db._read_ctx() as conn:
            result['conversations'] = [dict(row) for row in conn.execute(
                f'SELECT id,title FROM sessions WHERE ({authority.db._MEU_SYNC_PROFILE_SCOPE}) ORDER BY started_at DESC LIMIT 200')]
            roots = {item['id']: item['root'] for item in store._records(conn)}
        for item in result['projects']:
            item['directory'] = roots[item['id']]
        return result
    return await asyncio.to_thread(read)


@router.post('')
async def select(request: Request, selection: Selection):
    from hermes_cli.web_routers.mobile_preview import _scope
    _, authority = _scope(request)
    try:
        result = await asyncio.to_thread(ProjectStore(authority.db).register,
            selection.directory, selection.name, [selection.session_id])
        return result
    except (ValueError, LookupError) as error:
        raise HTTPException(409, str(error)) from None


@router.post('/{project_id}/return')
async def request_return(request: Request, project_id: str):
    from hermes_cli.web_routers.mobile_preview import _scope
    _, authority = _scope(request)
    try:
        return await asyncio.to_thread(ProjectStore(authority.db).request_return, project_id)
    except (ValueError, LookupError) as error:
        raise HTTPException(409, str(error)) from None
