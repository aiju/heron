-- nfib: the number of calls the naive Fibonacci makes. Strict Int
-- arithmetic and calls; the strictness analysis makes it call by value.

nfib :: Int -> Int
nfib n = if n < 2 then 1 else nfib (n - 1) + nfib (n - 2) + 1

main input = "nfib 22 = " ++ show (nfib 22) ++ "\n"
