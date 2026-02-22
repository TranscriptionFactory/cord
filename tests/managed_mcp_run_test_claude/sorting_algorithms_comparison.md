# Testing Managed MCP Run in Claude Code (v2.1.50 Opus 4.6)

---
# Task: Sorting Algorithms: QuickSort, MergeSort, and HeapSort — Comparative Analysis

> **Prompt:** Use cord's run_tree to research 3 different sorting algorithms and compare their time complexity


--- 

# OUTPUT:

## Algorithm Summaries

**QuickSort** selects a "pivot" element, partitions the array so smaller elements go left and larger go right, then recursively sorts each partition. Fastest in practice due to cache-friendly access, but has an O(n²) worst case with poor pivot selection.

**MergeSort** recursively splits an array in half, sorts each half, then merges them. Guarantees O(n log n) in all cases and is **stable** (preserves order of equal elements). Costs O(n) extra space.

**HeapSort** builds a max-heap, then repeatedly extracts the maximum into its sorted position. Guarantees O(n log n) in-place (O(1) extra space), but poor cache locality makes it slowest in practice.

## Comparison Table

| Property              | QuickSort    | MergeSort  | HeapSort   |
| --------------------- | ------------ | ---------- | ---------- |
| **Best Case**         | O(n log n)   | O(n log n) | O(n log n) |
| **Average Case**      | O(n log n)   | O(n log n) | O(n log n) |
| **Worst Case**        | **O(n²)**    | O(n log n) | O(n log n) |
| **Space Complexity**  | O(log n) avg | **O(n)**   | **O(1)**   |
| **In-Place?**         | Yes          | No         | Yes        |
| **Stable?**           | No           | **Yes**    | No         |
| **Cache Performance** | Excellent    | Good       | Poor       |
| **Practical Speed**   | Fastest      | Moderate   | Slowest    |

## Decision Guide

| Situation                                 | Recommended                      |
| ----------------------------------------- | -------------------------------- |
| General-purpose in-memory sort            | **QuickSort** (randomized pivot) |
| Stability required                        | **MergeSort**                    |
| Sorting linked lists                      | **MergeSort**                    |
| Data exceeds RAM (external sort)          | **MergeSort**                    |
| Memory-constrained + worst-case guarantee | **HeapSort**                     |
| Top-k extraction                          | **HeapSort**                     |

## Key Takeaway

All three algorithms achieve O(n log n) average-case performance, but they differ critically in their **guarantees**, **memory usage**, and **practical speed**:

- **QuickSort** is the fastest in practice but has an O(n²) worst case.
- **MergeSort** guarantees O(n log n) always and is the only stable sort, at the cost of O(n) extra space.
- **HeapSort** guarantees O(n log n) with O(1) space, but poor cache behavior makes it slowest in practice.

Modern production sort implementations (Python's **Timsort**, C++ STL's **Introsort**) are hybrids that combine the strengths of these algorithms to avoid their individual weaknesses.
