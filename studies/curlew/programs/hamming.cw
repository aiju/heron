-- Hamming numbers (2^i 3^j 5^k), in order: one lazy list defined in
-- terms of itself, merged from three scaled copies. Every element is a
-- thunk evaluated once and shared three times.

hamming :: [Int]
hamming = 1 : merge3 (map (* 2) hamming) (map (* 3) hamming) (map (* 5) hamming)

merge3 :: [Int] -> [Int] -> [Int] -> [Int]
merge3 xs ys zs = merge xs (merge ys zs)

merge :: [Int] -> [Int] -> [Int]
merge xxs@(x:xs) yys@(y:ys)
  | x < y = x : merge xs yys
  | x > y = y : merge xxs ys
  | otherwise = x : merge xs ys

main input = "the first 20: " ++ show (take 20 hamming) ++ "\n"
  ++ "the 1000th: " ++ show (hamming !! 999) ++ "\n"
  ++ "below a million: " ++ show (length (takeWhile (< 1000000) hamming)) ++ "\n"
