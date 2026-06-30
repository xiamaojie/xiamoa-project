a = [9,[8,1,5,4]]

b = a[1]
c = a[0]

print(a)
for i in range(len(b)):
    for j in range(1,len(b)):
        if b[i]+b[j] == c:
            print("值是{},{}".format(b[i] ,b[j]))
            print("下标是{},{}".format(i ,j))
