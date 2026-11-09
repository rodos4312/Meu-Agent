"""Personal transfer roots use the same pinned handles as the owner's browser."""
from pathlib import Path

from fastapi import HTTPException

from hermes_cli.meu_transfer_paths import TransferDirectory, directory_identity
from hermes_cli.meu_transfers import TransferFolder


def create_space_folder(authority, name):
    parent = TransferFolder(authority)
    root, generation = parent.grant()
    with TransferDirectory(root, []) as directory:
        parent.grant(generation)
        try:
            directory.mkdir(name)
        except FileExistsError:
            raise HTTPException(409, 'This folder already exists. Choose another name.') from None
        with TransferDirectory(root, [name]) as child:
            identity = list(child.identity)
        parent.grant(generation)
    return {'root_id': generation, 'root_path': str(root),
            'root_identity': list(directory_identity(root)), 'identity': identity}


def space_root(authority, space):
    root, generation = TransferFolder(authority).grant()
    if Path(space['root_path']) != root or list(directory_identity(root)) != space['root_identity']:
        raise HTTPException(409, 'Select the original shared folder on the PC to use this personal space.')
    return root, generation


class SpaceTransferFolder(TransferFolder):
    def __init__(self, authority, registry, device_id):
        super().__init__(authority)
        self.registry = registry
        self.device_id = device_id

    def grant(self, expected=None):
        _device, space = self.registry.scope(self.authority.profile_id, self.device_id)
        if space.get('owner') is True:
            return super().grant(expected)
        root, generation = space_root(self.authority, space)
        # A different person's generation is never a valid capability here.
        scoped_generation = f"{generation}:{space['id']}"
        if expected is not None and expected != scoped_generation:
            raise HTTPException(409, 'The personal folder changed. Refresh before transferring.')
        with TransferDirectory(root, [space['name']]) as child:
            if list(child.identity) != space['identity']:
                raise HTTPException(409, 'The personal folder changed. Check it on the PC.')
        return Path(root) / space['name'], scoped_generation


class MobileTransferFolder(TransferFolder):
    """Keep admitted legacy transfers revocable after an in-place owner enrolment."""
    def __init__(self, preview):
        super().__init__(preview.authority)
        self.preview = preview

    def grant(self, expected=None):
        preview = self.preview
        if preview.personal_devices:
            return SpaceTransferFolder(self.authority, preview.personal_devices, preview.device_id).grant(expected)
        return super().grant(expected)
