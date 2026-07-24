import time

# Large input
n = int(1e6)
nums0 = (4*[0]+[2]+4*[0])*(9*(n//10)) + [0]*(n//10)

# --- Your boundary-tightening solution ---
def sort_colors_optimized(nums):
    n = len(nums)
    firstNot0 = 0
    lastNot2 = n-1

    # Tighten boundaries
    while firstNot0 <= lastNot2 and nums[firstNot0] == 0:
        firstNot0 += 1
    while lastNot2 >= firstNot0 and nums[lastNot2] == 2:
        lastNot2 -= 1

    i = firstNot0
    while i <= lastNot2:
        num = nums[i]
        if num == 1:
            i += 1
            continue

        if num == 2:
            nums[i], nums[lastNot2] = nums[lastNot2], 2
            lastNot2 -= 1
            while lastNot2 >= firstNot0 and nums[lastNot2] == 2:
                lastNot2 -= 1
            if i == firstNot0 and nums[i] == 0:
                firstNot0 += 1
                while firstNot0 <= lastNot2 and nums[firstNot0] == 0:
                    firstNot0 += 1
                i = firstNot0
                continue

        if num == 0:
            if i != firstNot0:
                nums[i], nums[firstNot0] = nums[firstNot0], 0
            firstNot0 += 1
            while firstNot0 <= lastNot2 and nums[firstNot0] == 0:
                firstNot0 += 1
            i = max(i+1, firstNot0)
            continue

        i += 1

# --- Classic DNF solution ---
def sort_colors_dnf(nums):
    low, mid, high = 0, 0, len(nums)-1
    while mid <= high:
        num = nums[mid]
        if num == 0:
            if nums[low] != 0:
                nums[low], nums[mid] = 0, nums[low]
            low += 1
            mid += 1
        elif nums == 1:
            mid += 1
        else:  # num == 2
            if nums[high] != 2:
                nums[high], nums[mid] = 2, nums[high]
            high -= 1

# Benchmark
import copy
nums1 = copy.deepcopy(nums0)
nums2 = copy.deepcopy(nums0)

t0 = time.time()
sort_colors_optimized(nums1)
t1 = time.time()
sort_colors_dnf(nums2)
t2 = time.time()

print("Optimized time: {:.6f}s".format(t1-t0))
print("DNF time:       {:.6f}s".format(t2-t1))

#print(nums0)
#print(nums1)

# Verify correctness
if(nums1 != nums2):
    print("Solutions don't match!")
