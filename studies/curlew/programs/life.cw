-- Conway's game of life on a small torus, as lists of lists of Bool:
-- a glider and a few still lifes, for some generations, printed as text.

type Board = [[Bool]]

width, height :: Int
width = 16
height = 12

start :: Board
start = [[(r, c) `elem` cells | c <- [0 .. width - 1]] | r <- [0 .. height - 1]]
  where cells = [(1, 2), (2, 3), (3, 1), (3, 2), (3, 3),            -- a glider
                 (8, 10), (8, 11), (9, 10), (9, 11),                 -- a block
                 (5, 12), (6, 12), (7, 12)]                          -- a blinker

at :: Board -> Int -> Int -> Bool
at b r c = (b !! (r `mod` height)) !! (c `mod` width)

step :: Board -> Board
step b = [[rule (at b r c) (neighbours r c) | c <- [0 .. width - 1]] | r <- [0 .. height - 1]]
  where neighbours r c = length [() | dr <- [-1, 0, 1], dc <- [-1, 0, 1],
                                      (dr, dc) /= (0, 0), at b (r + dr) (c + dc)]
        rule alive n = n == 3 || (alive && n == 2)

render :: Board -> String
render b = unlines [[if x then '#' else '.' | x <- row] | row <- b]

main input = concat [ "generation " ++ show n ++ ":\n" ++ render g
                    | (n, g) <- zip [0 :: Int ..] (take 21 (iterate step start)), n `mod` 10 == 0 ]
             ++ "live cells after 20: " ++ show (length (filter id (concat (iterate step start !! 20)))) ++ "\n"
