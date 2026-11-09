"""Cached grid paths and a spatial neighborhood index for army steering."""
from __future__ import annotations

from collections import defaultdict
import heapq
import math
import pygame


class SpatialIndex:
    def __init__(self, actors, cell=140):
        self.cell = cell
        self.cells = defaultdict(list)
        for actor in actors:
            self.cells[self.key(actor.pos)].append(actor)

    def key(self, pos):
        return math.floor(pos[0] / self.cell), math.floor(pos[1] / self.cell)

    def near(self, pos, radius=180):
        x, y = self.key(pos)
        span = math.ceil(radius / self.cell)
        return [actor for dx in range(-span, span + 1) for dy in range(-span, span + 1)
                for actor in self.cells.get((x + dx, y + dy), ())
                if actor.pos.distance_squared_to(pos) <= radius * radius]


class Navigator:
    def __init__(self, obstacles, cell=36):
        self.cell = cell
        self.obstacles = [o.inflate(48, 48) for o in obstacles]
        self.blocked = set()
        for x in range(92):
            for y in range(18, 30):
                point = self.point((x, y))
                if any(o.collidepoint(point) for o in self.obstacles):
                    self.blocked.add((x, y))
        self.cache = {}

    def key(self, pos):
        return max(1, min(90, int(pos[0] // self.cell))), max(18, min(29, int(pos[1] // self.cell)))

    def point(self, key):
        return pygame.Vector2((key[0] + .5) * self.cell, (key[1] + .5) * self.cell)

    def path(self, start, goal):
        start, goal = self.key(start), self.key(goal)
        if goal in self.blocked:
            free = [(x, y) for x in range(max(1, goal[0] - 4), min(91, goal[0] + 5))
                    for y in range(max(18, goal[1] - 4), min(30, goal[1] + 5)) if (x, y) not in self.blocked]
            if not free:
                return []
            goal = min(free, key=lambda k: (k[0] - goal[0]) ** 2 + (k[1] - goal[1]) ** 2)
        cache_key = start, goal
        if cache_key in self.cache:
            return list(self.cache[cache_key])
        frontier = [(0, start)]
        parents = {start: None}
        cost = {start: 0}
        while frontier:
            _, current = heapq.heappop(frontier)
            if current == goal:
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (-1, 1), (1, -1)):
                nxt = current[0] + dx, current[1] + dy
                if not (1 <= nxt[0] <= 90 and 18 <= nxt[1] <= 29) or nxt in self.blocked:
                    continue
                if dx and dy and ((current[0] + dx, current[1]) in self.blocked
                                  or (current[0], current[1] + dy) in self.blocked):
                    continue
                new_cost = cost[current] + (1.414 if dx and dy else 1)
                if new_cost < cost.get(nxt, float("inf")):
                    cost[nxt] = new_cost
                    parents[nxt] = current
                    priority = new_cost + math.hypot(goal[0] - nxt[0], goal[1] - nxt[1])
                    heapq.heappush(frontier, (priority, nxt))
        if goal not in parents:
            return []
        result = []
        node = goal
        while node != start:
            result.append(self.point(node))
            node = parents[node]
        result.reverse()
        if len(self.cache) > 500:
            self.cache.clear()
        self.cache[cache_key] = tuple(result)
        return result

    def waypoint(self, actor, target, now):
        target = pygame.Vector2(target)
        if not any(o.clipline(actor.pos, target) for o in self.obstacles):
            actor.nav_path = []
            return target
        if (not getattr(actor, "nav_path", None) or
                (now >= getattr(actor, "nav_refresh", 0) and target.distance_squared_to(actor.nav_goal) > 70 ** 2)):
            actor.nav_path = self.path(actor.pos, target)
            actor.nav_goal = target.copy()
            actor.nav_refresh = now + .8
        while actor.nav_path and actor.pos.distance_squared_to(actor.nav_path[0]) < 20 ** 2:
            actor.nav_path.pop(0)
        return actor.nav_path[0] if actor.nav_path else actor.pos
