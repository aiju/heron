-- input: input/wordfreq.txt
-- Word frequencies of the input: the words, lower-cased, into a binary
-- search tree (Ord on strings: compare through the list instance), then
-- the most frequent, sorted. Reads its input lazily.

data Map = Tip | Bin Map String Int Map

insertW :: String -> Map -> Map
insertW w Tip = Bin Tip w 1 Tip
insertW w (Bin l k n r) = case compare w k of
  LT -> Bin (insertW w l) k n r
  GT -> Bin l k n (insertW w r)
  EQ -> Bin l k (n + 1) r

toListM :: Map -> [(String, Int)]
toListM m = go m []
  where go Tip acc = acc
        go (Bin l k n r) acc = go l ((k, n) : go r acc)

clean :: String -> String
clean = map toLower . filter isAlpha

main input = show (length ws) ++ " words, " ++ show (length counts) ++ " different\n"
             ++ unlines [w ++ " " ++ show n | (w, n) <- take 25 counts]
  where ws = filter (not . null) (map clean (words input))
        m = foldl' (flip insertW) Tip ws
        counts = sortBy (\(a, x) (b, y) -> compare (y, a) (x, b)) (toListM m)
