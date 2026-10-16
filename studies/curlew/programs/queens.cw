-- The n queens: every way to place n queens on an n by n board, by list
-- comprehensions over partial solutions.

queens :: Int -> [[Int]]
queens n = go n
  where
    go 0 = [[]]
    go k = [q : qs | qs <- go (k - 1), q <- [1 .. n], safe q qs]

safe :: Int -> [Int] -> Bool
safe q qs = and [q /= c && abs (q - c) /= d | (d, c) <- zip [1 ..] qs]

showBoard :: Int -> [Int] -> String
showBoard n qs = unlines [[if c == q then 'Q' else '.' | c <- [1 .. n]] | q <- qs]

main input = concatMap report [4 .. 8] ++ showBoard 8 (head (queens 8))
  where report n = show n ++ " queens: " ++ show (length (queens n)) ++ " solutions\n"
