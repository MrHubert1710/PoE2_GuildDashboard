"""League-specific paths without importing application configuration."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
from urllib.parse import quote


def league_directory_name(league):
    """Keep ordinary league names readable, escape filesystem/path characters."""
    if not isinstance(league, str) or not league.strip():
        raise ValueError('LEAGUE_NAME must be a non-empty string')
    name = quote(league, safe=' -_.')
    # quote always leaves dots unescaped; Windows also trims trailing spaces.
    while name.endswith(('.', ' ')):
        ending = '%2E' if name[-1] == '.' else '%20'
        name = name[:-1] + ending
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                *(f'LPT{i}' for i in range(1, 10))}
    if name.split('.')[0].upper() in reserved:
        name = f'%{ord(name[0]):02X}' + name[1:]
    if len(name) > 160:
        name = name[:100] + '--' + hashlib.sha256(league.encode('utf-8')).hexdigest()[:32]
    return name


@dataclass(frozen=True)
class LeaguePaths:
    logs: Path
    reports: Path

    @property
    def charts(self):
        return self.reports / 'charts'

    @property
    def prices(self):
        return self.reports / 'price_cache'

    @property
    def latest_dashboard(self):
        return self.reports / 'GuildReport_Latest.html'


def league_paths(league, base_directory='.'):
    name = league_directory_name(league)
    base = Path(base_directory)
    return LeaguePaths(base / 'logs' / name, base / 'stash_reports' / name)
