from pathlib import Path
from typing import List, Tuple, Union
import pygame

class Spritesheet:
    def __init__(self, filepath: Path, sprite_size: Tuple[int, int], spacing: Tuple[int, int] = (0, 0), scale: Tuple[int, int] = None) -> None:
        """Initialize the spritesheet.

        Args:
            filepath (Path): Path to the spritesheet image file.
            sprite_size (Tuple[int, int]): Width and height of each sprite in the sheet.
            spacing (Tuple[int, int], optional): Spacing between each sprite (row spacing, column spacing). Defaults to (0, 0).
            scale (Tuple[int, int], optional): Rescale each sprite to the given size. Defaults to None.
        """
        self._sheet = pygame.image.load(filepath).convert_alpha()
        self._sprite_size = sprite_size
        self._spacing = spacing
        self._scale = scale

    def get_sprite(self, loc: Tuple[int, int], colorkey: Union[pygame.Color, int, None] = None) -> pygame.Surface:
        """Load a specific sprite from the spritesheet.

        Args:
            loc (Tuple[int, int]): Location of the sprite in the sheet (row, column).
            colorkey (Union[pygame.Color, int, None], optional): Color to be treated as transparent. Defaults to None.

        Returns:
            pygame.Surface: The sprite image.
        """
        x = loc[1] * (self._sprite_size[0] + self._spacing[0])
        y = loc[0] * (self._sprite_size[1] + self._spacing[1])

        rect = pygame.Rect(x, y, *self._sprite_size)
        image = pygame.Surface(self._sprite_size, pygame.SRCALPHA).convert_alpha()
        image.blit(self._sheet, (0, 0), rect)

        if colorkey is not None:
            if colorkey == -1:
                colorkey = image.get_at((0, 0))
            image.set_colorkey(colorkey, pygame.RLEACCEL)

        if self._scale:
            image = pygame.transform.scale(image, self._scale)
        
        return image

    def get_sprites(self, locs: List[Tuple[int, int]], colorkey: Union[pygame.Color, int, None] = None) -> List[pygame.Surface]:
        """Load multiple sprites from the spritesheet.

        Args:
            locs (List[Tuple[int, int]]): List of locations of the sprites in the sheet (row, column).
            colorkey (Union[pygame.Color, int, None], optional): Color to be treated as transparent. Defaults to None.

        Returns:
            List[pygame.Surface]: List of sprite images.
        """
