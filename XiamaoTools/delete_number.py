array = [1,2,2,3]
new_list = []
for i in range(len(array)):
    if array[i] not in new_list:
        new_list.append(array[i])
    else:
        print(array[i])
print(new_list)