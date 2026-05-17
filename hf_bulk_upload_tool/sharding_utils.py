#!/usr/bin/env python3
"""
Transparent sharding utilities for BirdNET dataset uploads.

Handles the splitting of large species directories (>10k files) for HF compliance,
while keeping them transparent to validation code.

Sharding format:
  Elaenia albiceps/           (original, <10k files)
  Elaenia albiceps__shard_00/ (part 1, if original had >10k)
  Elaenia albiceps__shard_01/ (part 2)
  ...
  
When reading in validation: transparently combines all shards into a single virtual directory.
"""

import os
from pathlib import Path
from typing import Dict, List, Tuple


SHARD_SEPARATOR = "__shard_"
MAX_FILES_PER_DIR = 9500  # Stay below 10k limit with safety margin


def is_shard_folder(folder_name: str) -> Tuple[bool, str]:
    """
    Check if a folder name is a shard and extract the base species name.
    
    Returns:
        (is_shard: bool, base_species_name: str)
    """
    if SHARD_SEPARATOR not in folder_name:
        return False, folder_name
    
    base = folder_name.split(SHARD_SEPARATOR)[0]
    return True, base


def get_all_shards(base_species_path: Path) -> List[Path]:
    """
    Get all shards for a species, including the base folder if it exists.
    
    Args:
        base_species_path: Path to the base species folder (e.g., Species Name/)
    
    Returns:
        List of all shard paths for this species, sorted by shard index
    """
    parent = base_species_path.parent
    base_name = base_species_path.name
    
    shards = []
    
    # Add the base folder if it exists and is not empty
    if base_species_path.is_dir():
        files = list(base_species_path.glob("*"))
        if files:
            shards.append(base_species_path)
    
    # Find all shards (Elaenia albiceps__shard_00, __shard_01, etc.)
    shard_pattern = f"{base_name}{SHARD_SEPARATOR}*"
    shard_folders = sorted(parent.glob(shard_pattern))
    
    shards.extend(shard_folders)
    return shards


def iter_files_all_shards(base_species_path: Path):
    """
    Generator that yields all files from a species and all its shards.
    
    Args:
        base_species_path: Path to the base species folder
    
    Yields:
        Tuple of (file_path, relative_path_from_base_species)
    """
    shards = get_all_shards(base_species_path)
    
    for shard_path in shards:
        if not shard_path.is_dir():
            continue
        
        for file_path in shard_path.rglob("*"):
            if file_path.is_file():
                # Keep the relative structure from within the shard
                rel_from_shard = file_path.relative_to(shard_path)
                yield file_path, rel_from_shard


def should_shard_directory(directory_path: Path) -> bool:
    """
    Check if a directory should be sharded (has >MAX_FILES_PER_DIR files).
    
    Args:
        directory_path: Path to the directory
    
    Returns:
        True if should be sharded
    """
    if not directory_path.is_dir():
        return False
    
    count = sum(1 for _ in directory_path.rglob("*") if _.is_file())
    return count > MAX_FILES_PER_DIR


def shard_directory(source_dir: Path, dest_parent: Path) -> List[Path]:
    """
    Shard a large directory into multiple folders respecting the 10k file limit.
    
    Args:
        source_dir: Source directory to shard (e.g., "Elaenia albiceps/")
        dest_parent: Destination parent folder (staging root)
    
    Returns:
        List of created shard paths (destination folders)
    
    Example:
        shards = shard_directory(
            Path("Elaenia albiceps"),
            Path("staging/audio")
        )
        # Creates:
        #   staging/audio/Elaenia albiceps__shard_00/
        #   staging/audio/Elaenia albiceps__shard_01/
        #   ...
    """
    if not source_dir.is_dir():
        raise ValueError(f"Source directory does not exist: {source_dir}")
    
    dest_parent.mkdir(parents=True, exist_ok=True)
    base_name = source_dir.name
    
    # Collect all files
    all_files = sorted([f for f in source_dir.rglob("*") if f.is_file()])
    
    if not all_files:
        return []
    
    shards = []
    current_shard_idx = 0
    current_shard_count = 0
    current_shard_dir = None
    
    for file_path in all_files:
        # Create new shard if needed
        if current_shard_count >= MAX_FILES_PER_DIR or current_shard_dir is None:
            shard_name = f"{base_name}{SHARD_SEPARATOR}{current_shard_idx:02d}"
            current_shard_dir = dest_parent / shard_name
            current_shard_dir.mkdir(parents=True, exist_ok=True)
            shards.append(current_shard_dir)
            current_shard_count = 0
            current_shard_idx += 1
        
        # Copy file preserving directory structure
        rel_path = file_path.relative_to(source_dir)
        dest_file = current_shard_dir / rel_path
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Create symlink or hardlink instead of copying to save space
        if os.name == "nt":
            # Windows: use hardlink
            os.link(str(file_path), str(dest_file))
        else:
            # Unix: use symlink
            os.symlink(file_path, dest_file)
        
        current_shard_count += 1
    
    return shards


def get_species_map(staging_audio_dir: Path) -> Dict[str, List[Path]]:
    """
    Build a map of all species and their shards in the staging directory.
    
    Args:
        staging_audio_dir: Path to the staging audio directory (audio/)
    
    Returns:
        Dict mapping base species name -> list of shard paths
    
    Example:
        {
            "Elaenia albiceps": [
                Path("staging/audio/Elaenia albiceps__shard_00"),
                Path("staging/audio/Elaenia albiceps__shard_01"),
            ],
            "Other species": [
                Path("staging/audio/Other species"),
            ]
        }
    """
    if not staging_audio_dir.is_dir():
        return {}
    
    species_map = {}
    processed = set()
    
    for item in sorted(staging_audio_dir.iterdir()):
        if item.name in processed:
            continue
        
        is_shard, base_name = is_shard_folder(item.name)
        
        if is_shard:
            # This is a shard, process its base species
            if base_name not in species_map:
                species_map[base_name] = get_all_shards(staging_audio_dir / base_name)
            processed.add(item.name)
        elif item.is_dir():
            # This is a regular species folder (non-shard)
            if base_name not in species_map:
                species_map[base_name] = get_all_shards(item)
            processed.add(base_name)
    
    return species_map


# ===== Validation Helper =====

class TransparentSpeciesReader:
    """
    Helper for reading sharded species in validation code.
    
    Transparently combines all shards of a species into a single iterable view.
    
    Usage:
        reader = TransparentSpeciesReader(Path("dataset/audio"))
        for species_name, files in reader.iter_species():
            for file_path in files:
                # Process file
                pass
    """
    
    def __init__(self, dataset_audio_dir: Path):
        """
        Args:
            dataset_audio_dir: Path to the dataset's audio directory
        """
        self.audio_dir = Path(dataset_audio_dir)
        self._species_cache = None
    
    def get_species_list(self) -> List[str]:
        """Get list of all species (base names, deduped)."""
        species_map = get_species_map(self.audio_dir)
        return sorted(species_map.keys())
    
    def get_files_for_species(self, species_name: str) -> List[Path]:
        """
        Get all files for a species, combining all shards.
        
        Args:
            species_name: Base species name (e.g., "Elaenia albiceps")
        
        Returns:
            List of all file paths from this species (all shards combined)
        """
        species_map = get_species_map(self.audio_dir)
        if species_name not in species_map:
            return []
        
        files = []
        for shard_dir in species_map[species_name]:
            shard_files = sorted([f for f in shard_dir.rglob("*") if f.is_file()])
            files.extend(shard_files)
        
        return sorted(files)
    
    def iter_species(self):
        """
        Iterate over all species and their files.
        
        Yields:
            Tuple of (species_name: str, files: List[Path])
        """
        species_map = get_species_map(self.audio_dir)
        
        for species_name in sorted(species_map.keys()):
            files = self.get_files_for_species(species_name)
            yield species_name, files
    
    def iter_species_with_metadata(self):
        """
        Iterate over species with metadata (total files, shard count).
        
        Yields:
            Tuple of (species_name: str, files: List[Path], metadata: dict)
        """
        species_map = get_species_map(self.audio_dir)
        
        for species_name in sorted(species_map.keys()):
            shards = species_map[species_name]
            files = self.get_files_for_species(species_name)
            
            metadata = {
                "num_files": len(files),
                "num_shards": len(shards),
                "shard_dirs": shards,
            }
            
            yield species_name, files, metadata
